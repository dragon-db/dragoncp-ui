#!/usr/bin/env python3
"""
DragonCP Authentication Routes
Handles login, logout, token verification, and refresh
"""

from flask import Blueprint, jsonify, request, g
from auth import (
    verify_credentials, 
    generate_token, 
    generate_refresh_token,
    validate_token,
    get_token_from_request,
    require_auth,
    get_token_remaining_time,
    is_auth_configured
)

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/auth/login', methods=['POST'])
def api_login():
    """
    Authenticate user and return JWT tokens.
    
    Request body:
    {
        "username": "admin",
        "password": "your-password"
    }
    
    Response:
    {
        "status": "success",
        "token": "eyJ...",
        "refresh_token": "eyJ...",
        "expires_at": "2024-01-01T12:00:00Z",
        "user": "admin"
    }
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
    
    # Verify credentials
    if not verify_credentials(username, password):
        print(f"🔒 Failed login attempt for user: {username}")
        return jsonify({
            'status': 'error',
            'message': 'Invalid username or password',
            'code': 'INVALID_CREDENTIALS'
        }), 401
    
    # Generate tokens
    access_token, access_expiry = generate_token(username)
    refresh_token, refresh_expiry = generate_refresh_token(username)
    
    print(f"✅ User '{username}' logged in successfully")
    
    return jsonify({
        'status': 'success',
        'message': 'Login successful',
        'token': access_token,
        'refresh_token': refresh_token,
        'expires_at': access_expiry.isoformat(),
        'refresh_expires_at': refresh_expiry.isoformat(),
        'user': username
    })


@auth_bp.route('/auth/logout', methods=['POST'])
@require_auth
def api_logout():
    """
    Logout user (client-side token invalidation).
    
    Note: JWT tokens are stateless, so logout is handled client-side
    by removing the token. This endpoint exists for consistency and
    potential future server-side token blacklisting.
    """
    username = g.current_user
    print(f"🔒 User '{username}' logged out")
    
    return jsonify({
        'status': 'success',
        'message': 'Logout successful'
    })


@auth_bp.route('/auth/verify', methods=['GET'])
def api_verify():
    """
    Verify if current token is valid.
    
    Response:
    {
        "status": "success",
        "valid": true,
        "user": "admin",
        "remaining_seconds": 3600
    }
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
    
    remaining = get_token_remaining_time(token)
    
    return jsonify({
        'status': 'success',
        'valid': True,
        'user': payload.get('sub'),
        'remaining_seconds': remaining
    })


@auth_bp.route('/auth/refresh', methods=['POST'])
def api_refresh():
    """
    Refresh access token using refresh token.
    
    Request body:
    {
        "refresh_token": "eyJ..."
    }
    
    Response:
    {
        "status": "success",
        "token": "eyJ...",
        "expires_at": "2024-01-01T12:00:00Z"
    }
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
    
    username = payload.get('sub')
    
    # Generate new access token
    access_token, access_expiry = generate_token(username)
    
    print(f"🔄 Token refreshed for user: {username}")
    
    return jsonify({
        'status': 'success',
        'message': 'Token refreshed successfully',
        'token': access_token,
        'expires_at': access_expiry.isoformat(),
        'user': username
    })


@auth_bp.route('/auth/status', methods=['GET'])
def api_auth_status():
    """
    Get authentication system status.
    Useful for checking if auth is configured before showing login form.
    """
    configured = is_auth_configured()
    
    return jsonify({
        'status': 'success',
        'auth_configured': configured,
        'message': 'Authentication is configured' if configured else 'Authentication not configured'
    })
