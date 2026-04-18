#!/usr/bin/env python3
"""
DragonCP Webhook Authentication Module

Provides HMAC signature verification and source IP whitelisting for
webhook receiver endpoints (/api/webhook/movies, /api/webhook/series,
/api/webhook/anime).

Authentication Logic Matrix:
┌─────────────────┬───────────────────┬──────────────────────────────────────────────┐
│ WEBHOOK_SECRET  │ WEBHOOK_ALLOWED_IPS│ Behavior                                     │
├─────────────────┼───────────────────┼──────────────────────────────────────────────┤
│ Not set         │ Not set           │ Allow all + WARNING log (backward compat)    │
│ Not set         │ Set               │ IP check only - whitelisted pass, else 403   │
│ Set             │ Not set           │ Signature check only - valid sig or 401      │
│ Set             │ Set               │ Either passes - valid IP OR valid sig         │
└─────────────────┴───────────────────┴──────────────────────────────────────────────┘

Backward Compatibility:
    If neither WEBHOOK_SECRET nor WEBHOOK_ALLOWED_IPS is configured, all
    requests are allowed through with a warning log. This prevents breaking
    existing setups on upgrade.

IP Whitelisting Safety:
    IP whitelisting is safe for DragonCP's private-network deployment model
    (Tailscale/LAN). TCP handshake prevents IP spoofing. For internet-facing
    deployments, HMAC signature verification should be the primary mechanism
    with IP whitelisting as a supplementary layer.
"""

import os
import hmac
import hashlib
import ipaddress
import functools
import logging
from typing import Dict, List, Optional

from flask import request, jsonify

logger = logging.getLogger(__name__)

# ===== CONFIGURATION =====

# Cache for loaded webhook config
_webhook_config_cache: Optional[Dict[str, str]] = None
# Track whether we've logged the auth status at startup
_auth_status_logged = False


def _load_env_file() -> Dict[str, str]:
    """
    Load configuration from dragoncp_env.env or .env file.
    Mirrors the pattern from auth.py to avoid circular imports.
    """
    config = {}
    script_dir = os.path.dirname(os.path.abspath(__file__))

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
                break
            except Exception as e:
                logger.error("Error loading webhook config from %s: %s", env_file, e)

    return config


def _get_webhook_config() -> Dict[str, Optional[str]]:
    """
    Get webhook authentication configuration.

    Returns:
        Dict with 'secret' and 'allowed_ips' keys.
        Values are None if not configured.
    """
    global _webhook_config_cache

    if _webhook_config_cache is not None:
        return _webhook_config_cache

    env_config = _load_env_file()

    secret = (
        env_config.get('WEBHOOK_SECRET')
        or os.environ.get('WEBHOOK_SECRET')
    ) or None

    allowed_ips_raw = (
        env_config.get('WEBHOOK_ALLOWED_IPS')
        or os.environ.get('WEBHOOK_ALLOWED_IPS')
    ) or None

    _webhook_config_cache = {
        'secret': secret if secret else None,
        'allowed_ips_raw': allowed_ips_raw if allowed_ips_raw else None,
    }

    return _webhook_config_cache


def _parse_allowed_ips(raw: str) -> List:
    """
    Parse comma-separated IP addresses and CIDR ranges.

    Supports:
        - Individual IPs: "192.168.1.100"
        - CIDR ranges: "192.168.1.0/24"
        - IPv6: "::1", "fd00::/8"
        - Mixed: "192.168.1.100,10.0.0.0/24,::1"

    Args:
        raw: Comma-separated string of IPs/CIDRs

    Returns:
        List of ipaddress.IPv4Network/IPv6Network objects
    """
    networks = []
    for entry in raw.split(','):
        entry = entry.strip()
        if not entry:
            continue
        try:
            # Try parsing as a network (CIDR notation)
            # strict=False allows host bits set (e.g., 192.168.1.100/24)
            network = ipaddress.ip_network(entry, strict=False)
            networks.append(network)
        except ValueError:
            logger.warning(
                "WEBHOOK_AUTH: Invalid IP/CIDR entry ignored: '%s'", entry
            )
    return networks


def is_ip_allowed(client_ip: str, allowed_networks: List) -> bool:
    """
    Check if a client IP is within any of the allowed networks.

    Args:
        client_ip: The client's IP address string
        allowed_networks: List of ipaddress network objects from _parse_allowed_ips()

    Returns:
        True if the IP is in any allowed network, False otherwise
    """
    if not client_ip or not allowed_networks:
        return False

    try:
        addr = ipaddress.ip_address(client_ip)
    except ValueError:
        logger.warning(
            "WEBHOOK_AUTH: Could not parse client IP: '%s'", client_ip
        )
        return False

    for network in allowed_networks:
        try:
            if addr in network:
                return True
        except TypeError:
            # IPv4 address checked against IPv6 network or vice versa
            continue

    return False


def verify_webhook_signature(payload_bytes: bytes, signature_header: str, secret: str) -> bool:
    """
    Verify HMAC-SHA256 signature of webhook payload.

    The signature header format is: "sha256=<hex_digest>"
    This follows the convention used by GitHub, GitLab, and other webhook providers.

    Args:
        payload_bytes: Raw request body bytes
        signature_header: Value of X-DragonCP-Signature header
        secret: The shared HMAC secret

    Returns:
        True if signature is valid, False otherwise
    """
    if not payload_bytes or not signature_header or not secret:
        return False

    # Parse the signature header - expected format: "sha256=<hex_digest>"
    if not signature_header.startswith('sha256='):
        logger.warning(
            "WEBHOOK_AUTH: Invalid signature format (expected 'sha256=...'): %s",
            signature_header[:20]
        )
        return False

    provided_signature = signature_header[7:]  # Strip "sha256=" prefix

    # Compute expected signature
    expected_signature = hmac.new(
        secret.encode('utf-8'),
        payload_bytes,
        hashlib.sha256
    ).hexdigest()

    # Constant-time comparison to prevent timing attacks
    return hmac.compare_digest(provided_signature, expected_signature)


def _log_auth_status():
    """
    Log the webhook authentication status at startup/first use.
    Called once to inform the operator of the current security posture.
    """
    global _auth_status_logged

    if _auth_status_logged:
        return

    _auth_status_logged = True

    config = _get_webhook_config()
    has_secret = config['secret'] is not None
    has_ips = config['allowed_ips_raw'] is not None

    if not has_secret and not has_ips:
        logger.warning(
            "WEBHOOK_AUTH: Webhook endpoints are UNAUTHENTICATED. "
            "Configure WEBHOOK_SECRET and/or WEBHOOK_ALLOWED_IPS in "
            "dragoncp_env.env for security."
        )
        print(
            "WARNING: Webhook endpoints are UNAUTHENTICATED. "
            "Configure WEBHOOK_SECRET and/or WEBHOOK_ALLOWED_IPS in "
            "dragoncp_env.env for security."
        )
    elif has_ips and not has_secret:
        networks = _parse_allowed_ips(config['allowed_ips_raw'])
        logger.info(
            "WEBHOOK_AUTH: IP whitelist enabled (%d entries). "
            "No HMAC signature verification configured.",
            len(networks)
        )
        print(f"Webhook auth: IP whitelist enabled ({len(networks)} entries)")
    elif has_secret and not has_ips:
        logger.info(
            "WEBHOOK_AUTH: HMAC signature verification enabled (X-DragonCP-Signature). "
            "No IP whitelist configured."
        )
        print("Webhook auth: HMAC signature verification enabled")
    else:
        networks = _parse_allowed_ips(config['allowed_ips_raw'])
        logger.info(
            "WEBHOOK_AUTH: Defense-in-depth enabled - HMAC signature + "
            "IP whitelist (%d entries). Request passes if EITHER check succeeds.",
            len(networks)
        )
        print(f"Webhook auth: HMAC signature + IP whitelist ({len(networks)} entries)")


def require_webhook_auth(f):
    """
    Decorator for webhook receiver endpoints that enforces authentication
    based on the configured WEBHOOK_SECRET and/or WEBHOOK_ALLOWED_IPS.

    This decorator MUST be applied to all webhook receiver endpoints
    (POST /api/webhook/movies, /api/webhook/series, /api/webhook/anime).
    Place it AFTER @route() and BEFORE the function definition.

    Authentication matrix (see module docstring for full table):
    - Neither configured: allow all with warning (backward compatible)
    - IP only: whitelist check
    - Secret only: signature check
    - Both: either passes (OR logic)

    Note on request.get_data():
        This decorator calls request.get_data() to capture raw bytes for HMAC
        verification. Flask caches the raw data internally, so subsequent calls
        to request.json in the route handler still work correctly.

    Note on reverse proxy:
        Client IP is read from request.remote_addr. If DragonCP is deployed
        behind a reverse proxy (nginx, Traefik, Cloudflared), apply
        werkzeug.middleware.proxy_fix.ProxyFix to the WSGI app so that
        request.remote_addr reflects the real client IP, not the proxy's.
    """
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        # Log auth status on first invocation
        _log_auth_status()

        config = _get_webhook_config()
        has_secret = config['secret'] is not None
        has_ips = config['allowed_ips_raw'] is not None

        # === CASE 1: Neither configured - allow all (backward compatible) ===
        if not has_secret and not has_ips:
            return f(*args, **kwargs)

        # Gather request context for auth checks
        # SECURITY: Read raw body BEFORE request.json to capture bytes for HMAC.
        # Flask caches the data internally so request.json still works later.
        raw_body = request.get_data()

        # Get client IP
        # NOTE: If behind a reverse proxy, ensure ProxyFix middleware is applied
        # so request.remote_addr returns the real client IP.
        client_ip = request.remote_addr
        signature_header = request.headers.get('X-DragonCP-Signature', '')

        ip_allowed = False
        sig_valid = False

        # Check IP whitelist if configured
        if has_ips:
            allowed_networks = _parse_allowed_ips(config['allowed_ips_raw'])
            ip_allowed = is_ip_allowed(client_ip, allowed_networks)

        # Check signature if configured
        if has_secret:
            sig_valid = verify_webhook_signature(raw_body, signature_header, config['secret'])

        # === CASE 2: IP only - whitelist check ===
        if has_ips and not has_secret:
            if ip_allowed:
                return f(*args, **kwargs)
            else:
                logger.warning(
                    "WEBHOOK_AUTH: Request from unauthorized IP %s rejected "
                    "(not in WEBHOOK_ALLOWED_IPS whitelist). Endpoint: %s",
                    client_ip, request.path
                )
                return jsonify({
                    "status": "error",
                    "message": "Unauthorized: source IP not in whitelist",
                    "code": "WEBHOOK_IP_REJECTED"
                }), 403

        # === CASE 3: Secret only - signature check ===
        if has_secret and not has_ips:
            if sig_valid:
                return f(*args, **kwargs)
            else:
                if not signature_header:
                    logger.warning(
                        "WEBHOOK_AUTH: Missing X-DragonCP-Signature header from %s. "
                        "Endpoint: %s",
                        client_ip, request.path
                    )
                    return jsonify({
                        "status": "error",
                        "message": "Unauthorized: missing X-DragonCP-Signature header",
                        "code": "WEBHOOK_SIGNATURE_MISSING"
                    }), 401
                else:
                    logger.warning(
                        "WEBHOOK_AUTH: Invalid signature from %s. Endpoint: %s",
                        client_ip, request.path
                    )
                    return jsonify({
                        "status": "error",
                        "message": "Unauthorized: invalid webhook signature",
                        "code": "WEBHOOK_SIGNATURE_INVALID"
                    }), 401

        # === CASE 4: Both configured - either passes (OR logic) ===
        if has_secret and has_ips:
            if ip_allowed or sig_valid:
                if ip_allowed:
                    logger.debug(
                        "WEBHOOK_AUTH: Request from whitelisted IP %s allowed. "
                        "Endpoint: %s",
                        client_ip, request.path
                    )
                else:
                    logger.debug(
                        "WEBHOOK_AUTH: Valid signature from %s allowed. "
                        "Endpoint: %s",
                        client_ip, request.path
                    )
                return f(*args, **kwargs)
            else:
                logger.warning(
                    "WEBHOOK_AUTH: Request from %s rejected - IP not whitelisted "
                    "AND signature %s. Endpoint: %s",
                    client_ip,
                    "missing" if not signature_header else "invalid",
                    request.path
                )
                return jsonify({
                    "status": "error",
                    "message": "Unauthorized: IP not whitelisted and signature verification failed",
                    "code": "WEBHOOK_AUTH_FAILED"
                }), 403

        # Fallback (should not reach here, but safety net)
        return f(*args, **kwargs)

    return decorated_function


def reload_webhook_config():
    """
    Force reload of webhook configuration from env file.

    Call this after updating dragoncp_env.env to pick up changes
    without restarting the application.
    """
    global _webhook_config_cache, _auth_status_logged
    _webhook_config_cache = None
    _auth_status_logged = False
    logger.info("WEBHOOK_AUTH: Configuration reloaded")
