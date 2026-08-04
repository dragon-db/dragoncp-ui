#!/usr/bin/env python3
"""
DragonCP Authentication Module
JWT-based authentication over accounts held in the database.

Accounts live in the `admin_account` table and are maintained from the server
with `scripts/manage_admins.py`. The credentials in the environment file remain
as a fallback: they are accepted only while the database holds no account that
can sign in, which covers a fresh install, an upgrade from the single-account
setup, and the case where every account has been disabled and someone needs a
way back in.

Two properties are worth stating plainly, because both were absent before and
both are what makes an activity trail trustworthy:

    Sessions do not outlive account changes. Every token carries the account's
    `token_version`, and every authenticated request compares it against the
    row. Disabling an account, changing its password, or renaming it bumps that
    number and retires the tokens already issued.

    Every request resolves an actor. `g.current_actor` names who is responsible,
    and it is the same vocabulary background jobs use, so nothing that happens
    in this application is anonymous.
"""

import os
import jwt
import functools
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Dict, Any
from flask import request, jsonify, g
from werkzeug.security import check_password_hash, generate_password_hash

from actor import admin_actor


# ===== CONFIGURATION =====

# Cache for loaded env config
_env_config_cache: Optional[Dict[str, str]] = None

#: Set by app.py once the database exists. Left as None in tests and in any
#: context without one, where the environment-file account is the only account.
_account_store = None


def set_account_store(store) -> None:
    """Give the auth layer its account table. Called once during startup."""
    global _account_store
    _account_store = store


def get_account_store():
    """The account table, or None when running without a database."""
    return _account_store


def _load_env_file() -> Dict[str, str]:
    """
    Load configuration from dragoncp_env.env or .env file.
    This is used for auth config to avoid circular imports with DragonCPConfig.
    """
    global _env_config_cache

    if _env_config_cache is not None:
        return _env_config_cache

    config = {}
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Try dragoncp_env.env first, then .env
    env_files = [
        os.path.join(script_dir, 'dragoncp_env.env'),
        os.path.join(script_dir, '.env'),
    ]

    for env_file in env_files:
        if os.path.exists(env_file):
            try:
                with open(env_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            key, value = line.split('=', 1)
                            config[key.strip()] = value.strip().strip('"').strip("'")
                print(f"🔐 Auth config loaded from: {env_file}")
                break
            except Exception as e:
                print(f"⚠️  Error loading auth config from {env_file}: {e}")

    _env_config_cache = config
    return config


def reset_env_config_cache() -> None:
    """Drop the cached environment file. For tests."""
    global _env_config_cache
    _env_config_cache = None


def get_auth_config() -> Dict[str, Any]:
    """Get authentication configuration from env file"""
    env_config = _load_env_file()

    jwt_secret = (
        env_config.get('JWT_SECRET_KEY')
        or env_config.get('SECRET_KEY')
        or os.environ.get('JWT_SECRET_KEY')
        or os.environ.get('SECRET_KEY')
    )
    if not jwt_secret:
        raise RuntimeError(
            "Missing JWT secret. Set JWT_SECRET_KEY (preferred) or SECRET_KEY in config/environment."
        )

    def _int(key: str, default: int) -> int:
        """
        A whole number from the environment file, or the default.

        A typo in one of these used to raise straight out of get_auth_config(),
        which every sign-in and every authenticated request calls — so
        `LOGIN_MAX_ATTEMPTS=five` locked the whole application out rather than
        just being ignored.
        """
        raw = env_config.get(key)
        if raw is None or str(raw).strip() == '':
            return default
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            print(f"⚠️  {key}={raw!r} is not a whole number; using {default}")
            return default

    return {
        'username': env_config.get('DRAGONCP_USERNAME', 'admin'),
        'password_hash': env_config.get('DRAGONCP_PASSWORD_HASH', ''),
        'password_plain': env_config.get('DRAGONCP_PASSWORD', ''),
        'jwt_secret': jwt_secret,
        'jwt_expiry_hours': _int('JWT_EXPIRY_HOURS', 24),
        'jwt_algorithm': 'HS256',
        'login_max_attempts': _int('LOGIN_MAX_ATTEMPTS', 5),
        'login_window_minutes': _int('LOGIN_WINDOW_MINUTES', 15),
        'login_lockout_minutes': _int('LOGIN_LOCKOUT_MINUTES', 15),
    }


# ===== IDENTITY =====

#: Where a signed-in identity came from. Tokens carry this so a session minted
#: against the fallback account can be told apart from a real one.
SOURCE_DATABASE = 'db'
SOURCE_ENV = 'env'


def _identity_from_account(account: Dict) -> Dict[str, Any]:
    """Turn an account row into the identity carried through a request."""
    return {
        'account_id': account['id'],
        'username': account['username'],
        'role': account.get('role', 'admin'),
        'token_version': int(account.get('token_version', 1)),
        'must_change_password': bool(account.get('must_change_password', False)),
        'source': SOURCE_DATABASE,
    }


def identity_for_account(account: Dict) -> Dict[str, Any]:
    """Public form of the account-row-to-identity conversion, for route code."""
    return _identity_from_account(account)


def _env_identity() -> Optional[Dict[str, Any]]:
    """The environment-file account, if one is configured."""
    config = get_auth_config()
    if not (config['password_hash'] or config['password_plain']):
        return None
    return {
        'account_id': None,
        'username': config['username'],
        'role': 'admin',
        'token_version': 0,
        'must_change_password': False,
        'source': SOURCE_ENV,
    }


def env_fallback_active() -> bool:
    """
    Whether the environment-file account is currently accepted.

    True while no account in the database can sign in. Adding the first enabled
    account switches this off, and any session issued against the fallback stops
    validating at that moment — which is the intended handover, not a bug.
    """
    if _account_store is None:
        return True
    try:
        return _account_store.count_enabled() == 0
    except Exception:
        # A database that cannot be read must not lock everyone out.
        print("⚠️  Could not read the account table; falling back to environment credentials")
        return True


# ===== PASSWORD VERIFICATION =====

#: A real hash to compare against when the named account does not exist, so a
#: wrong username costs the same time as a wrong password and cannot be
#: distinguished by how quickly it is rejected. Built on first use — hashing is
#: deliberately slow and this should not be paid at import.
_dummy_hash: Optional[str] = None


def _waste_time_like_a_real_check(password: str) -> None:
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = generate_password_hash('dragoncp-no-such-account', method='pbkdf2:sha256')
    check_password_hash(_dummy_hash, password or '')


def _check_env_password(password: str) -> bool:
    """Verify a password against the environment file's credentials."""
    config = get_auth_config()

    if config['password_hash']:
        return check_password_hash(config['password_hash'], password)

    if config['password_plain']:
        # Constant-time comparison so the fallback does not leak the password
        # one character at a time. Compared as bytes: compare_digest refuses
        # str containing non-ASCII, so a password with an accent in it raised
        # TypeError out of the sign-in handler instead of simply not matching.
        import hmac
        return hmac.compare_digest(
            password.encode('utf-8'), config['password_plain'].encode('utf-8')
        )

    return False


def authenticate(username: str, password: str) -> Optional[Dict[str, Any]]:
    """
    Check a username and password, returning the identity when they are good.

    Database accounts take precedence. The environment-file account is consulted
    only while `env_fallback_active()`, so once real accounts exist it stops
    being a way in.
    """
    username = (username or '').strip()

    if not username or not password:
        return None

    if _account_store is not None:
        account = _account_store.find_by_username(username)

        if account is not None:
            if not account['is_active']:
                # Disabled accounts fail like a wrong password rather than
                # announcing that the account exists but is switched off.
                _waste_time_like_a_real_check(password)
                print(f"🔒 Sign-in refused for disabled account: {username}")
                return None

            if check_password_hash(account['password_hash'], password):
                return _identity_from_account(account)

            return None

    if env_fallback_active():
        env_identity = _env_identity()
        if env_identity is None:
            print("⚠️  No password configured in ENV (DRAGONCP_PASSWORD or DRAGONCP_PASSWORD_HASH)")
            return None

        if username.lower() != env_identity['username'].lower():
            _waste_time_like_a_real_check(password)
            return None

        if _check_env_password(password):
            return env_identity

        return None

    # No such account, and the fallback is not in play.
    _waste_time_like_a_real_check(password)
    return None


def verify_credentials(username: str, password: str) -> bool:
    """Whether a username and password are valid. Prefer `authenticate()`."""
    return authenticate(username, password) is not None


def hash_password(password: str) -> str:
    """Generate a password hash for storing against an account"""
    return generate_password_hash(password, method='pbkdf2:sha256')


# ===== JWT TOKEN MANAGEMENT =====

def _build_payload(identity: Dict[str, Any], token_type: str, expiry: datetime) -> Dict[str, Any]:
    """The claims every token carries."""
    return {
        'sub': identity['username'],
        'uid': identity['account_id'],
        'tv': identity['token_version'],
        'src': identity['source'],
        'role': identity.get('role', 'admin'),
        'iat': datetime.now(timezone.utc),
        'exp': expiry,
        'type': token_type,
    }


def generate_token(identity: Dict[str, Any]) -> Tuple[str, datetime]:
    """
    Generate a JWT access token for an authenticated identity.
    Returns tuple of (token, expiry_datetime)
    """
    config = get_auth_config()

    expiry = datetime.now(timezone.utc) + timedelta(hours=config['jwt_expiry_hours'])
    payload = _build_payload(identity, 'access', expiry)
    token = jwt.encode(payload, config['jwt_secret'], algorithm=config['jwt_algorithm'])

    return token, expiry


def generate_refresh_token(identity: Dict[str, Any]) -> Tuple[str, datetime]:
    """
    Generate a refresh token with longer expiry.
    Returns tuple of (token, expiry_datetime)
    """
    config = get_auth_config()

    # Refresh token lasts 7 days
    expiry = datetime.now(timezone.utc) + timedelta(days=7)
    payload = _build_payload(identity, 'refresh', expiry)
    token = jwt.encode(payload, config['jwt_secret'], algorithm=config['jwt_algorithm'])

    return token, expiry


def validate_token(token: str, token_type: str = 'access') -> Optional[Dict[str, Any]]:
    """
    Validate a JWT token and return the payload if valid.
    Returns None if token is invalid or expired.

    This checks the token itself only — signature, expiry and type. Whether the
    account behind it may still act is `resolve_identity()`.
    """
    config = get_auth_config()

    try:
        payload = jwt.decode(
            token,
            config['jwt_secret'],
            algorithms=[config['jwt_algorithm']]
        )

        # Verify token type
        if payload.get('type') != token_type:
            print(f"⚠️  Token type mismatch: expected {token_type}, got {payload.get('type')}")
            return None

        return payload

    except jwt.ExpiredSignatureError:
        print("⚠️  Token has expired")
        return None
    except jwt.InvalidTokenError as e:
        print(f"⚠️  Invalid token: {e}")
        return None


# ===== ACCOUNT STATE AT REQUEST TIME =====

#: Returned alongside a rejection so the caller knows why.
REASON_OK = 'OK'
REASON_UNKNOWN_ACCOUNT = 'UNKNOWN_ACCOUNT'
REASON_DISABLED = 'ACCOUNT_DISABLED'
REASON_REVOKED = 'SESSION_REVOKED'


def resolve_identity(payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Confirm the account behind a valid token may still act, and return it.

    The account row is read fresh on every request, deliberately and without a
    cache — the same way application settings are read. That read is what makes
    a disable or a password change take effect at once instead of whenever the
    person's token happens to run out.

    Returns (identity, REASON_OK) or (None, reason).
    """
    source = payload.get('src', SOURCE_ENV)

    if source == SOURCE_ENV:
        # A fallback session is only good while the fallback is still in force.
        if not env_fallback_active():
            return None, REASON_REVOKED

        env_identity = _env_identity()
        if env_identity is None:
            return None, REASON_UNKNOWN_ACCOUNT

        if (payload.get('sub') or '').lower() != env_identity['username'].lower():
            return None, REASON_UNKNOWN_ACCOUNT

        return env_identity, REASON_OK

    if _account_store is None:
        return None, REASON_UNKNOWN_ACCOUNT

    account_id = payload.get('uid')
    account = (
        _account_store.find_by_id(account_id)
        if account_id is not None
        else _account_store.find_by_username(payload.get('sub'))
    )

    if account is None:
        return None, REASON_UNKNOWN_ACCOUNT

    if not account['is_active']:
        return None, REASON_DISABLED

    if int(payload.get('tv', -1)) != int(account['token_version']):
        return None, REASON_REVOKED

    return _identity_from_account(account), REASON_OK


def _bind_identity_to_request(identity: Dict[str, Any], payload: Dict[str, Any]) -> None:
    """Put the authenticated identity where the rest of a request can find it."""
    g.current_user = identity['username']
    g.current_account_id = identity['account_id']
    g.current_account = identity
    g.current_actor = admin_actor(identity['username'], identity['account_id'])
    g.token_payload = payload


def _clear_identity_from_request() -> None:
    g.current_user = None
    g.current_account_id = None
    g.current_account = None
    g.current_actor = None
    g.token_payload = None


def _is_websocket_upgrade_request() -> bool:
    """
    Detect whether this request is a WebSocket upgrade request.
    """
    upgrade_header = request.headers.get('Upgrade', '').lower()
    if upgrade_header == 'websocket':
        return True

    if str(request.environ.get('HTTP_UPGRADE', '')).lower() == 'websocket':
        return True

    # Some WSGI servers expose a websocket object in environ.
    if request.environ.get('wsgi.websocket') is not None:
        return True

    return False


def get_token_from_request() -> Optional[str]:
    """
    Extract JWT token from request.
    For normal HTTP requests, only Authorization header (Bearer) is accepted.
    Query parameter token is accepted only for WebSocket upgrade requests.
    """
    # Try Authorization header first
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header[7:]  # Remove 'Bearer ' prefix

    # Allow query token only during websocket upgrade requests
    if _is_websocket_upgrade_request():
        token = request.args.get('token')
        if token:
            return token

    return None


# ===== ROUTE PROTECTION DECORATOR =====

def _protect(f, allow_password_change_pending: bool):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        token = get_token_from_request()

        if not token:
            return jsonify({
                'status': 'error',
                'message': 'Authentication required',
                'code': 'AUTH_REQUIRED'
            }), 401

        payload = validate_token(token, token_type='access')

        if not payload:
            return jsonify({
                'status': 'error',
                'message': 'Invalid or expired token',
                'code': 'INVALID_TOKEN'
            }), 401

        identity, reason = resolve_identity(payload)

        if identity is None:
            messages = {
                REASON_DISABLED: 'This account has been disabled',
                REASON_REVOKED: 'This session is no longer valid. Please sign in again.',
                REASON_UNKNOWN_ACCOUNT: 'This account no longer exists',
            }
            print(f"🔒 Rejected request from '{payload.get('sub')}': {reason}")
            return jsonify({
                'status': 'error',
                'message': messages.get(reason, 'Not authorised'),
                'code': reason
            }), 401

        # An account still on the password it was handed is a credential two
        # people know, so anything it does is not unambiguously theirs. Refuse
        # the work rather than record it against a shared secret; the browser
        # holds them at a password screen for the same reason, and this is what
        # makes that more than a suggestion.
        if identity.get('must_change_password') and not allow_password_change_pending:
            return jsonify({
                'status': 'error',
                'message': 'Choose your own password before continuing.',
                'code': 'PASSWORD_CHANGE_REQUIRED'
            }), 403

        _bind_identity_to_request(identity, payload)

        return f(*args, **kwargs)

    return decorated_function


def require_auth(f):
    """
    Decorator to protect routes requiring authentication.

    Sets g.current_user (the username), g.current_account_id (the stable id),
    g.current_account (the whole identity) and g.current_actor (who to blame)
    before calling the view.

    Refuses with 403 `PASSWORD_CHANGE_REQUIRED` while the account still owes a
    first password change.
    """
    return _protect(f, allow_password_change_pending=False)


def require_auth_pending_ok(f):
    """
    As `require_auth`, but reachable while a first password change is owed.

    Only for the handful of endpoints that change or end that state — otherwise
    the requirement would lock people out of the very screen that satisfies it.
    """
    return _protect(f, allow_password_change_pending=True)


def optional_auth(f):
    """
    Decorator for routes that work with or without authentication.
    Sets g.current_user if authenticated, None otherwise.
    """
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        token = get_token_from_request()

        if token:
            payload = validate_token(token, token_type='access')
            if payload:
                identity, reason = resolve_identity(payload)
                if identity is not None:
                    _bind_identity_to_request(identity, payload)
                else:
                    _clear_identity_from_request()
            else:
                _clear_identity_from_request()
        else:
            _clear_identity_from_request()

        return f(*args, **kwargs)

    return decorated_function


# ===== WEBSOCKET AUTHENTICATION =====

def validate_websocket_token(auth_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Validate token from WebSocket connection auth data.

    Returns the identity when the token is good *and* the account behind it may
    still act, None otherwise. Callers keep the returned account id and token
    version so a long-lived connection can be re-checked later.
    """
    token = auth_data.get('token') if auth_data else None

    if not token:
        return None

    payload = validate_token(token, token_type='access')

    if not payload:
        return None

    identity, _reason = resolve_identity(payload)

    return identity


def websocket_identity_still_valid(account_id: Optional[int], token_version: int, source: str) -> bool:
    """
    Whether a connection accepted earlier is still backed by a live account.

    A realtime connection authenticates once at handshake, so without this a
    disabled admin would keep receiving updates until they happened to
    disconnect. The cleanup thread calls this to close that gap.
    """
    if source == SOURCE_ENV:
        return env_fallback_active()

    if _account_store is None:
        return False

    if account_id is None:
        return False

    account = _account_store.find_by_id(account_id)

    if account is None or not account['is_active']:
        return False

    return int(account['token_version']) == int(token_version)


# ===== UTILITY FUNCTIONS =====

def get_token_remaining_time(token: str) -> Optional[int]:
    """
    Get remaining time in seconds before token expires.
    Returns None if token is invalid.
    """
    config = get_auth_config()

    try:
        # Decode without verification to get expiry
        payload = jwt.decode(
            token,
            config['jwt_secret'],
            algorithms=[config['jwt_algorithm']],
            options={'verify_exp': False}
        )

        exp = payload.get('exp')
        if exp:
            remaining = exp - datetime.now(timezone.utc).timestamp()
            return max(0, int(remaining))

        return None

    except jwt.InvalidTokenError:
        return None


def is_auth_configured() -> bool:
    """
    Whether anyone can sign in at all.

    True when the database holds an enabled account, or when the environment
    file still carries the fallback credentials.
    """
    if _account_store is not None:
        try:
            if _account_store.count_enabled() > 0:
                return True
        except Exception:
            pass

    return _env_identity() is not None
