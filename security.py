#!/usr/bin/env python3
"""
DragonCP Security Utilities

=== SECURITY BOUNDARY - READ THIS IF MODIFYING FILE OPERATIONS ===

All file operations in DragonCP MUST validate paths through these functions
before accessing the filesystem. This ensures that no webhook payload, API
request, or any external input can escape the configured media and backup
directories (MOVIE_PATH, TVSHOW_PATH, ANIME_PATH, *_DEST_PATH, BACKUP_PATH).

If you are adding NEW file operations to DragonCP, you MUST:
1. Validate individual path components with validate_path_component()
2. Validate fully-constructed paths with assert_path_within_bounds()
3. NEVER construct file paths from user/external input without validation
4. This applies to ALL operations: read, write, rename, delete, rsync, backup

The configured directory paths are the ONLY allowed filesystem scope.
Any path that resolves outside these directories MUST be rejected.

See also: webhook_auth.py for webhook endpoint authentication.
"""

import os
import logging

logger = logging.getLogger(__name__)


class PathTraversalError(ValueError):
    """
    Raised when a path traversal attempt is detected.

    SECURITY: This exception indicates that a user-supplied or webhook-supplied
    path component attempted to escape the configured directory boundaries.
    All callers should treat this as a security event and log it accordingly.

    Inherits from ValueError so that existing except-ValueError blocks in
    path_service.py catch it naturally, but callers can also catch it
    specifically for security logging.
    """
    pass


def validate_path_component(component: str) -> bool:
    """
    Validate a single path component (folder name, season name, episode filename).

    SECURITY: This function ensures individual path segments do not contain
    directory traversal sequences or path separators that could be used to
    escape the configured media/backup directory boundaries.

    A path component is a single segment of a path (e.g., a folder name or
    filename). It should NOT contain directory separators or parent-directory
    references.

    Allowed: "Season 01", "Movie Title (2024)", "Show - S01E01 - Title.mkv",
             names with unicode, colons, brackets, parens, etc.
    Rejected: "..", "../etc", "foo/bar", "foo\\bar", "", null bytes

    Args:
        component: A single path segment to validate

    Returns:
        True if the component is safe, False if it contains traversal patterns
    """
    if not component or not component.strip():
        return False

    # Reject null bytes (filesystem injection)
    if '\0' in component:
        logger.warning("SECURITY: Null byte detected in path component: %r", component)
        return False

    # Reject parent-directory references
    # Check for exact ".." or ".." embedded in segments like "..hidden"
    if component == '.' or component == '..':
        logger.warning("SECURITY: Dot/dot-dot path component rejected: %r", component)
        return False

    # Reject any component containing ".." as a directory traversal sequence
    # This catches "../../etc", "foo..bar/../baz" etc.
    if '..' in component:
        logger.warning("SECURITY: Path traversal sequence '..' detected in component: %r", component)
        return False

    # Reject path separators (both Unix and Windows)
    # A valid component should be a single directory/file name, never a sub-path
    if '/' in component or '\\' in component:
        logger.warning("SECURITY: Path separator detected in component: %r", component)
        return False

    return True


def validate_resolved_path(resolved_path: str, allowed_base_paths: list) -> bool:
    """
    Validate that a fully-constructed path resolves within one of the allowed
    base directories.

    SECURITY: This is the core path boundary check. It resolves symlinks and
    normalizes the path to ensure no traversal can escape the configured
    directory scope. This function MUST be called before any filesystem
    operation (read, write, rename, delete, rsync) on a path constructed
    from external input.

    The check uses os.path.realpath() which:
    - Resolves all symbolic links
    - Eliminates all ".." and "." references
    - Returns an absolute, canonical path

    Args:
        resolved_path: The fully-constructed path to validate
        allowed_base_paths: List of allowed base directory paths

    Returns:
        True if the path is within one of the allowed base directories,
        False otherwise
    """
    if not resolved_path or not allowed_base_paths:
        return False

    # Resolve to canonical absolute path (resolves symlinks, eliminates ..)
    real_path = os.path.realpath(resolved_path)

    for base in allowed_base_paths:
        if not base:
            continue
        # Resolve the base path too (in case it contains symlinks)
        real_base = os.path.realpath(base)

        # Check if the resolved path is the base itself or a child of it
        # SECURITY: We append os.sep to prevent "/home/user" matching "/home/username"
        if real_path == real_base or real_path.startswith(real_base + os.sep):
            return True

    return False


def assert_path_within_bounds(path: str, allowed_base_paths: list) -> str:
    """
    Assert that a path resolves within one of the allowed base directories.
    Raises PathTraversalError if the path escapes the configured boundaries.

    SECURITY: This is the preferred API for service-layer code. Use this
    instead of validate_resolved_path() when you want automatic error
    handling. All filesystem operations on paths derived from external input
    (webhooks, API requests, user input) MUST pass through this function.

    Args:
        path: The fully-constructed path to validate
        allowed_base_paths: List of allowed base directory paths

    Returns:
        The resolved (canonical) path for the caller to use

    Raises:
        PathTraversalError: If the path escapes the allowed boundaries
    """
    if not path:
        raise PathTraversalError("Empty path is not allowed")

    # Filter out empty/None base paths
    valid_bases = [b for b in allowed_base_paths if b]
    if not valid_bases:
        raise PathTraversalError(
            "No allowed base paths configured. Cannot validate path security boundary."
        )

    real_path = os.path.realpath(path)

    if not validate_resolved_path(real_path, valid_bases):
        logger.warning(
            "SECURITY: Path traversal blocked - path '%s' (resolved: '%s') "
            "escapes allowed boundaries: %s",
            path, real_path, valid_bases
        )
        raise PathTraversalError(
            f"Path '{path}' resolves outside allowed directories. "
            f"This may indicate a path traversal attempt."
        )

    return real_path


def validate_relative_path(relative_path: str) -> bool:
    """
    Validate a relative path (e.g., from a webhook rename event or backup file list).

    SECURITY: Relative paths from external sources (webhook payloads, API requests)
    can contain traversal sequences. This function validates that a relative path
    does not attempt to escape upward using ".." or start with an absolute path.

    Unlike validate_path_component(), this function DOES allow forward slashes
    (since relative paths like "Season 01/filename.mkv" are legitimate).
    It rejects: absolute paths, ".." sequences, null bytes.

    Args:
        relative_path: A relative file path to validate

    Returns:
        True if the relative path is safe, False otherwise
    """
    if not relative_path or not relative_path.strip():
        return False

    # Reject null bytes
    if '\0' in relative_path:
        logger.warning("SECURITY: Null byte detected in relative path: %r", relative_path)
        return False

    # Reject absolute paths
    if relative_path.startswith('/') or relative_path.startswith('\\'):
        logger.warning("SECURITY: Absolute path rejected as relative path: %r", relative_path)
        return False

    # On Windows, also reject drive letter paths like "C:\..."
    if len(relative_path) >= 2 and relative_path[1] == ':':
        logger.warning("SECURITY: Windows absolute path rejected: %r", relative_path)
        return False

    # Reject ".." traversal in any segment
    # Split on both Unix and Windows separators
    segments = relative_path.replace('\\', '/').split('/')
    for segment in segments:
        if segment == '..':
            logger.warning(
                "SECURITY: Directory traversal '..' detected in relative path: %r",
                relative_path
            )
            return False

    return True
