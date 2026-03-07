#!/usr/bin/env python3
"""
DragonCP Log Routes
Provides authenticated API access to backend log entries.
"""

import logging
import os
import re
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

from auth import require_auth
from logging_setup import get_log_file_path


logs_bp = Blueprint("logs", __name__)
logger = logging.getLogger("dragoncp.routes.logs")

DEFAULT_LIMIT = 200
MAX_LIMIT = 1000
MAX_SCAN_LINES = 20000
MIN_SCAN_LINES = 1000
LEVEL_PATTERN = re.compile(r"\|\s*(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s*\|")


def _normalize_level(value: str) -> str:
    if not value:
        return "ERROR"

    normalized = str(value).strip().upper()
    if normalized in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "ALL"}:
        return normalized
    return "ERROR"


def _parse_limit(value: str) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT

    if limit < 1:
        return DEFAULT_LIMIT
    return min(limit, MAX_LIMIT)


def _extract_level(log_line: str) -> str:
    match = LEVEL_PATTERN.search(log_line)
    if not match:
        return "INFO"
    return match.group(1)


def _level_matches(entry_level: str, requested_level: str) -> bool:
    if requested_level == "ALL":
        return True
    if requested_level == "ERROR":
        return entry_level in {"ERROR", "CRITICAL"}
    if requested_level == "WARNING":
        return entry_level in {"WARNING", "ERROR", "CRITICAL"}
    return entry_level == requested_level


def _tail_lines(file_path: Path, line_limit: int) -> list[str]:
    if line_limit <= 0:
        return []

    chunk_size = 8192
    buffer = bytearray()
    newline_count = 0

    with file_path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        cursor = handle.tell()

        while cursor > 0 and newline_count <= line_limit:
            read_size = min(chunk_size, cursor)
            cursor -= read_size
            handle.seek(cursor)
            chunk = handle.read(read_size)
            buffer[:0] = chunk
            newline_count = buffer.count(b"\n")

    text = buffer.decode("utf-8", errors="replace")
    lines = text.splitlines()

    if len(lines) > line_limit:
        return lines[-line_limit:]
    return lines


@logs_bp.route("/logs", methods=["GET"])
@require_auth
def api_logs():
    requested_level = _normalize_level(request.args.get("level", "ERROR"))
    limit = _parse_limit(request.args.get("limit", str(DEFAULT_LIMIT)))
    search_term = (request.args.get("search") or "").strip().lower()

    log_path = get_log_file_path()
    try:
        relative_log_path = str(log_path.relative_to(Path.cwd())) if log_path.is_absolute() else str(log_path)
    except ValueError:
        relative_log_path = str(log_path)

    if not log_path.exists():
        return jsonify(
            {
                "status": "success",
                "log_file": relative_log_path,
                "level": requested_level,
                "limit": limit,
                "lines": [],
                "line_count": 0,
                "message": "Log file is not created yet.",
            }
        )

    scan_limit = max(MIN_SCAN_LINES, min(limit * 25, MAX_SCAN_LINES))
    recent_lines = _tail_lines(log_path, scan_limit)

    filtered_entries = []
    for raw_line in reversed(recent_lines):
        if search_term and search_term not in raw_line.lower():
            continue

        level = _extract_level(raw_line)
        if not _level_matches(level, requested_level):
            continue

        filtered_entries.append({"level": level, "text": raw_line})
        if len(filtered_entries) >= limit:
            break

    filtered_entries.reverse()
    stat_info = log_path.stat()

    return jsonify(
        {
            "status": "success",
            "log_file": relative_log_path,
            "level": requested_level,
            "limit": limit,
            "line_count": len(filtered_entries),
            "size_bytes": stat_info.st_size,
            "last_modified": datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
            "lines": filtered_entries,
        }
    )


@logs_bp.route("/logs/download", methods=["GET"])
@require_auth
def api_logs_download():
    log_path = get_log_file_path()

    if not log_path.exists():
        return jsonify({"status": "error", "message": "Log file is not available."}), 404

    logger.info("Serving log download for %s", log_path)
    return send_file(
        log_path,
        as_attachment=True,
        download_name=log_path.name,
        mimetype="text/plain",
    )
