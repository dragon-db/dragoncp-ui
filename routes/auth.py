#!/usr/bin/env python3
"""
DragonCP Authentication Routes
Handles login, logout, token verification, refresh, and password changes.

Accounts themselves are not managed here. Creating, renaming, disabling and
resetting an administrator is done on the server with
`scripts/manage_admins.py` — see docs/operations/admin-accounts.md. The only
account change available through the browser is a person changing their own
password, which needs no privilege beyond being signed in.
"""

import login_guard
from activity_log import record, record_failure, record_refusal
from actor import SYSTEM_ACTOR, admin_actor
from flask import Blueprint, jsonify, request, g
from auth import (
    authenticate,
    generate_token,
    generate_refresh_token,
    validate_token,
    resolve_identity,
    identity_for_account,
    get_token_from_request,
    get_account_store,
    hash_password,
    require_auth_pending_ok,
    get_token_remaining_time,
    is_auth_configured,
    env_fallback_active,
    SOURCE_ENV,
    REASON_OK,
)
from models.admin_account import AdminAccountError, validate_password
from werkzeug.security import check_password_hash

auth_bp = Blueprint('auth', __name__)


def _client_address() -> str:
    """
    The caller's address, honouring a single proxy hop.

    Deployments put this behind a reverse proxy, where `remote_addr` is the
    proxy for everyone and would make the per-address limit lock the whole
    installation out at once.
    """
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or 'unknown'


def _session_response(identity, message='Login successful'):
    """Mint a fresh pair of tokens for an identity and describe the session."""
    access_token, access_expiry = generate_token(identity)
    refresh_token, refresh_expiry = generate_refresh_token(identity)

    return {
        'status': 'success',
        'message': message,
        'token': access_token,
        'refresh_token': refresh_token,
        'expires_at': access_expiry.isoformat(),
        'refresh_expires_at': refresh_expiry.isoformat(),
        'user': identity['username'],
        'account_id': identity['account_id'],
        'role': identity.get('role', 'admin'),
        'must_change_password': identity.get('must_change_password', False),
        'is_fallback_account': identity['source'] == SOURCE_ENV,
    }


@auth_bp.route('/auth/login', methods=['POST'])
def api_login():
    """
    Authenticate user and return JWT tokens.

    Request body:
    {
        "username": "admin",
        "password": "your-password"
    }

    Repeated failures are throttled by address and by username — see
    login_guard.py. A throttled caller gets 429 with `retry_after` in seconds
    and never reaches the password check.
    """
    # Check if auth is configured
    if not is_auth_configured():
        return jsonify({
            'status': 'error',
            'message': 'Authentication not configured. Set DRAGONCP_PASSWORD in environment.',
            'code': 'AUTH_NOT_CONFIGURED'
        }), 503

    # Validate request
    if not request.is_json:
        return jsonify({
            'status': 'error',
            'message': 'Content-Type must be application/json',
            'code': 'INVALID_CONTENT_TYPE'
        }), 400

    data = request.json
    if not data:
        return jsonify({
            'status': 'error',
            'message': 'Request body is required',
            'code': 'MISSING_BODY'
        }), 400

    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({
            'status': 'error',
            'message': 'Username and password are required',
            'code': 'MISSING_CREDENTIALS'
        }), 400

    address = _client_address()

    # Throttle before the credential check, so a locked-out caller cannot use
    # this endpoint to test passwords at all.
    wait = login_guard.retry_after(username, address)
    if wait is not None:
        print(f"🔒 Sign-in throttled for '{username}' from {address}; {wait}s remaining")
        record_refusal(
            'auth.login_blocked',
            f"Blocked a sign-in attempt for '{username}' after repeated failures",
            target_type='account', target_label=username,
            detail={'retry_after': wait}, actor=SYSTEM_ACTOR,
        )
        return jsonify({
            'status': 'error',
            'message': 'Too many failed sign-in attempts. Try again shortly.',
            'code': 'TOO_MANY_ATTEMPTS',
            'retry_after': wait,
        }), 429

    identity = authenticate(username, password)

    if identity is None:
        locked_for = login_guard.record_failure(username, address)
        print(f"🔒 Failed login attempt for user: {username} from {address}")
        record_failure(
            'auth.login_failed',
            f"Failed sign-in attempt for '{username}'",
            target_type='account', target_label=username, actor=SYSTEM_ACTOR,
        )

        if locked_for:
            return jsonify({
                'status': 'error',
                'message': 'Too many failed sign-in attempts. Try again shortly.',
                'code': 'TOO_MANY_ATTEMPTS',
                'retry_after': locked_for,
            }), 429

        return jsonify({
            'status': 'error',
            'message': 'Invalid username or password',
            'code': 'INVALID_CREDENTIALS'
        }), 401

    login_guard.record_success(username, address)

    signed_in = admin_actor(identity['username'], identity['account_id'])
    record('auth.login', f"Signed in", target_type='account',
           target_id=identity['account_id'], target_label=identity['username'],
           detail={'fallback_account': identity['source'] == SOURCE_ENV},
           actor=signed_in)

    store = get_account_store()
    if store is not None and identity['account_id'] is not None:
        store.record_login(identity['account_id'])

    if identity['source'] == SOURCE_ENV:
        print(
            f"⚠️  User '{identity['username']}' signed in with the environment-file "
            "fallback account — no administrators exist in the database"
        )
    else:
        print(f"✅ User '{identity['username']}' logged in successfully")

    return jsonify(_session_response(identity))


@auth_bp.route('/auth/logout', methods=['POST'])
@require_auth_pending_ok
def api_logout():
    """
    Logout user (client-side token invalidation).

    Note: JWT tokens are stateless, so logout is handled client-side
    by removing the token. Server-side revocation exists, but it is the
    account's token version — bumped when an account is disabled, renamed, or
    has its password changed — rather than a per-session record.
    """
    username = g.current_user
    print(f"🔒 User '{username}' logged out")
    record('auth.logout', 'Signed out', target_type='account',
           target_id=g.current_account_id, target_label=username)

    return jsonify({
        'status': 'success',
        'message': 'Logout successful'
    })


@auth_bp.route('/auth/verify', methods=['GET'])
def api_verify():
    """
    Verify if current token is valid.

    Reports invalid for a token that is well-formed but whose account has since
    been disabled, renamed, or had its password changed.
    """
    token = get_token_from_request()

    if not token:
        return jsonify({
            'status': 'success',
            'valid': False,
            'message': 'No token provided'
        })

    payload = validate_token(token, token_type='access')

    if not payload:
        return jsonify({
            'status': 'success',
            'valid': False,
            'message': 'Token is invalid or expired'
        })

    identity, reason = resolve_identity(payload)

    if identity is None:
        return jsonify({
            'status': 'success',
            'valid': False,
            'code': reason,
            'message': 'This session is no longer valid'
        })

    remaining = get_token_remaining_time(token)

    return jsonify({
        'status': 'success',
        'valid': True,
        'user': identity['username'],
        'account_id': identity['account_id'],
        'role': identity.get('role', 'admin'),
        'must_change_password': identity.get('must_change_password', False),
        'is_fallback_account': identity['source'] == SOURCE_ENV,
        'remaining_seconds': remaining
    })


@auth_bp.route('/auth/me', methods=['GET'])
@require_auth_pending_ok
def api_me():
    """Who the caller is signed in as."""
    identity = g.current_account

    return jsonify({
        'status': 'success',
        'user': identity['username'],
        'account_id': identity['account_id'],
        'role': identity.get('role', 'admin'),
        'must_change_password': identity.get('must_change_password', False),
        'is_fallback_account': identity['source'] == SOURCE_ENV,
        'can_change_password': identity['source'] != SOURCE_ENV,
    })


@auth_bp.route('/auth/refresh', methods=['POST'])
def api_refresh():
    """
    Refresh access token using refresh token.

    The account is re-checked here as well: a refresh token belonging to an
    account that has since been disabled or had its password changed will not
    mint a new access token.
    """
    if not request.is_json:
        return jsonify({
            'status': 'error',
            'message': 'Content-Type must be application/json',
            'code': 'INVALID_CONTENT_TYPE'
        }), 400

    data = request.json
    refresh_token = data.get('refresh_token') if data else None

    if not refresh_token:
        return jsonify({
            'status': 'error',
            'message': 'Refresh token is required',
            'code': 'MISSING_REFRESH_TOKEN'
        }), 400

    # Validate refresh token
    payload = validate_token(refresh_token, token_type='refresh')

    if not payload:
        return jsonify({
            'status': 'error',
            'message': 'Invalid or expired refresh token',
            'code': 'INVALID_REFRESH_TOKEN'
        }), 401

    identity, reason = resolve_identity(payload)

    if identity is None:
        print(f"🔒 Refused token refresh for '{payload.get('sub')}': {reason}")
        return jsonify({
            'status': 'error',
            'message': 'This session is no longer valid. Please sign in again.',
            'code': reason
        }), 401

    # Generate new access token
    access_token, access_expiry = generate_token(identity)

    print(f"🔄 Token refreshed for user: {identity['username']}")

    return jsonify({
        'status': 'success',
        'message': 'Token refreshed successfully',
        'token': access_token,
        'expires_at': access_expiry.isoformat(),
        'user': identity['username'],
        'must_change_password': identity.get('must_change_password', False),
    })


@auth_bp.route('/auth/change-password', methods=['POST'])
@require_auth_pending_ok
def api_change_password():
    """
    Change the signed-in user's own password.

    Nobody can change anyone else's password from the browser — that is what
    `scripts/manage_admins.py reset` is for. Changing a password retires every
    session the account had, including this one, so a fresh pair of tokens comes
    back in the response for the caller to adopt.
    """
    identity = g.current_account

    if identity['source'] == SOURCE_ENV:
        return jsonify({
            'status': 'error',
            'message': (
                'You are signed in with the fallback account from the environment '
                'file, which has no stored password to change. Create a real '
                'account on the server with scripts/manage_admins.py.'
            ),
            'code': 'FALLBACK_ACCOUNT'
        }), 400

    if not request.is_json:
        return jsonify({
            'status': 'error',
            'message': 'Content-Type must be application/json',
            'code': 'INVALID_CONTENT_TYPE'
        }), 400

    data = request.json or {}
    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')

    if not current_password or not new_password:
        return jsonify({
            'status': 'error',
            'message': 'Both the current and the new password are required',
            'code': 'MISSING_CREDENTIALS'
        }), 400

    store = get_account_store()
    if store is None:
        return jsonify({
            'status': 'error',
            'message': 'Account storage is unavailable',
            'code': 'STORE_UNAVAILABLE'
        }), 503

    account = store.find_by_id(identity['account_id'])

    if account is None:
        return jsonify({
            'status': 'error',
            'message': 'This account no longer exists',
            'code': 'UNKNOWN_ACCOUNT'
        }), 401

    if not check_password_hash(account['password_hash'], current_password):
        print(f"🔒 Password change refused for '{account['username']}': current password wrong")
        return jsonify({
            'status': 'error',
            'message': 'Your current password is not correct',
            'code': 'INVALID_CREDENTIALS'
        }), 401

    if new_password == current_password:
        return jsonify({
            'status': 'error',
            'message': 'The new password must be different from the current one',
            'code': 'PASSWORD_UNCHANGED'
        }), 400

    try:
        validate_password(new_password)
    except AdminAccountError as error:
        return jsonify({
            'status': 'error',
            'message': str(error),
            'code': 'WEAK_PASSWORD'
        }), 400

    updated = store.set_password(
        account['id'],
        hash_password(new_password),
        must_change_password=False,
    )

    print(f"🔑 Password changed for '{updated['username']}'; existing sessions retired")
    record('auth.password_change', 'Changed their own password',
           target_type='account', target_id=updated['id'],
           target_label=updated['username'])

    # The caller's token was just retired along with everyone else's. Hand back
    # a working pair so they are not bounced to the login screen for succeeding.
    return jsonify(_session_response(
        identity_for_account(updated),
        message='Password changed. Any other sessions for this account have been signed out.',
    ))


@auth_bp.route('/auth/status', methods=['GET'])
def api_auth_status():
    """
    Get authentication system status.
    Useful for checking if auth is configured before showing login form.
    """
    configured = is_auth_configured()
    store = get_account_store()

    return jsonify({
        'status': 'success',
        'auth_configured': configured,
        'account_count': store.count_all() if store is not None else 0,
        'using_fallback_account': env_fallback_active(),
        'message': 'Authentication is configured' if configured else 'Authentication not configured'
    })
