#!/usr/bin/env python3
"""
DragonCP Authentication Module
JWT-based authentication with ENV-based credentials
"""

import os
import jwt
import functools
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Dict, Any
from flask import request, jsonify, g
from werkzeug.security import check_password_hash, generate_password_hash


# ===== CONFIGURATION =====

# Cache for loaded env config
_env_config_cache: Optional[Dict[str, str]] = None


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


def get_auth_config() -> Dict[str, Any]:
    """Get authentication configuration from env file"""
    env_config = _load_env_file()
    
    return {
        'username': env_config.get('DRAGONCP_USERNAME', 'admin'),
        'password_hash': env_config.get('DRAGONCP_PASSWORD_HASH', ''),
        'password_plain': env_config.get('DRAGONCP_PASSWORD', ''),
        'jwt_secret': env_config.get('JWT_SECRET_KEY', env_config.get('SECRET_KEY', 'dragoncp-jwt-secret-change-me')),
        'jwt_expiry_hours': int(env_config.get('JWT_EXPIRY_HOURS', '24')),
        'jwt_algorithm': 'HS256'
    }


# ===== PASSWORD VERIFICATION =====

def verify_credentials(username: str, password: str) -> bool:
    """
    Verify username and password against ENV configuration.
    Supports both hashed and plain-text passwords from ENV.
    """
    config = get_auth_config()
    
    # Check username
    if username != config['username']:
        return False
    
    # Check password - support both hashed and plain-text
    if config['password_hash']:
        # Use hashed password if available
        return check_password_hash(config['password_hash'], password)
    elif config['password_plain']:
        # Fall back to plain-text comparison (for development/simple setups)
        # Using constant-time comparison to prevent timing attacks
        import hmac
        return hmac.compare_digest(password, config['password_plain'])
    else:
        # No password configured - deny access
        print("⚠️  No password configured in ENV (DRAGONCP_PASSWORD or DRAGONCP_PASSWORD_HASH)")
        return False


def hash_password(password: str) -> str:
    """Generate a password hash for storing in ENV"""
    return generate_password_hash(password, method='pbkdf2:sha256')


# ===== JWT TOKEN MANAGEMENT =====

def generate_token(username: str) -> Tuple[str, datetime]:
    """
    Generate a JWT token for authenticated user.
    Returns tuple of (token, expiry_datetime)
    """
    config = get_auth_config()
    
    expiry = datetime.now(timezone.utc) + timedelta(hours=config['jwt_expiry_hours'])
    
    payload = {
        'sub': username,
        'iat': datetime.now(timezone.utc),
        'exp': expiry,
        'type': 'access'
    }
    
    token = jwt.encode(payload, config['jwt_secret'], algorithm=config['jwt_algorithm'])
    
    return token, expiry


def generate_refresh_token(username: str) -> Tuple[str, datetime]:
    """
    Generate a refresh token with longer expiry.
    Returns tuple of (token, expiry_datetime)
    """
    config = get_auth_config()
    
    # Refresh token lasts 7 days
    expiry = datetime.now(timezone.utc) + timedelta(days=7)
    
    payload = {
        'sub': username,
        'iat': datetime.now(timezone.utc),
        'exp': expiry,
        'type': 'refresh'
    }
    
    token = jwt.encode(payload, config['jwt_secret'], algorithm=config['jwt_algorithm'])
    
    return token, expiry


def validate_token(token: str, token_type: str = 'access') -> Optional[Dict[str, Any]]:
    """
    Validate a JWT token and return the payload if valid.
    Returns None if token is invalid or expired.
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


def get_token_from_request() -> Optional[str]:
    """
    Extract JWT token from request.
    Supports Authorization header (Bearer token) and query parameter.
    """
    # Try Authorization header first
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header[7:]  # Remove 'Bearer ' prefix
    
    # Fall back to query parameter (useful for WebSocket connections)
    token = request.args.get('token')
    if token:
        return token
    
    return None


# ===== ROUTE PROTECTION DECORATOR =====

def require_auth(f):
    """
    Decorator to protect routes requiring authentication.
    Sets g.current_user with the authenticated username.
    """
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
        
        # Store authenticated user info in Flask's g object
        g.current_user = payload.get('sub')
        g.token_payload = payload
        
        return f(*args, **kwargs)
    
    return decorated_function


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
                g.current_user = payload.get('sub')
                g.token_payload = payload
            else:
                g.current_user = None
                g.token_payload = None
        else:
            g.current_user = None
            g.token_payload = None
        
        return f(*args, **kwargs)
    
    return decorated_function


# ===== WEBSOCKET AUTHENTICATION =====

def validate_websocket_token(auth_data: Dict[str, Any]) -> Optional[str]:
    """
    Validate token from WebSocket connection auth data.
    Returns username if valid, None otherwise.
    """
    token = auth_data.get('token') if auth_data else None
    
    if not token:
        return None
    
    payload = validate_token(token, token_type='access')
    
    if payload:
        return payload.get('sub')
    
    return None


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
    """Check if authentication is properly configured"""
    config = get_auth_config()
    return bool(config['password_hash'] or config['password_plain'])
