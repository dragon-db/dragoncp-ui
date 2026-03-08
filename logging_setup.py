#!/usr/bin/env python3
"""
DragonCP logging setup.
Provides centralized, thread-safe file logging for the backend.
"""

import atexit
import io
import inspect
import logging
import os
import queue
import re
import sys
import threading
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_LOG_FILE_NAME = "dragoncp_backend.log"
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"

_LOGGING_CONFIGURED = False
_LOG_QUEUE_LISTENER: Optional[QueueListener] = None
_LOG_QUEUE_HANDLER: Optional[QueueHandler] = None
_ORIGINAL_EXCEPTHOOK = sys.excepthook
_ORIGINAL_THREAD_EXCEPTHOOK = threading.excepthook
_ORIGINAL_STDOUT = sys.stdout
_ORIGINAL_STDERR = sys.stderr
_STD_STREAMS_REDIRECTED = False
_ATEXIT_REGISTERED = False

_SENSITIVE_MARKERS = ("SECRET", "PASSWORD", "TOKEN", "API_KEY", "WEBHOOK")
_AUTH_HEADER_PATTERN = re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+")
_BEARER_TOKEN_PATTERN = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+")
_ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_EXTERNAL_PATH_PREFIXES = {"venv", ".venv", "env", ".env", "node_modules"}


class StreamToLogger(io.TextIOBase):
    """File-like stream object that redirects writes to logging."""

    def __init__(self, logger_name: str, level: int):
        super().__init__()
        self._default_logger_name = logger_name
        self._level = level
        self._local = threading.local()

    def _get_local_state(self):
        if not hasattr(self._local, "buffer"):
            self._local.buffer = ""
        if not hasattr(self._local, "logger_name"):
            self._local.logger_name = self._default_logger_name
        return self._local

    def _resolve_caller_logger_name(self):
        frame = inspect.currentframe()
        caller_frame = frame.f_back if frame else None

        while caller_frame is not None:
            filename = caller_frame.f_code.co_filename
            if filename != __file__:
                break
            caller_frame = caller_frame.f_back

        if caller_frame is None:
            return self._default_logger_name

        try:
            caller_path = Path(caller_frame.f_code.co_filename).resolve()
            relative_path = caller_path.relative_to(PROJECT_ROOT)
            if relative_path.parts and relative_path.parts[0] in _EXTERNAL_PATH_PREFIXES:
                return self._default_logger_name
            if relative_path.suffix == ".py":
                module_parts = list(relative_path.with_suffix("").parts)
                if module_parts and module_parts[-1] == "__init__":
                    module_parts = module_parts[:-1]
                if module_parts:
                    return "dragoncp." + ".".join(module_parts)
        except (ValueError, OSError):
            pass

        return self._default_logger_name

    def _infer_log_level(self, message: str) -> int:
        upper_message = message.upper()

        if "CRITICAL" in upper_message:
            return logging.CRITICAL
        if "TRACEBACK" in upper_message or " EXCEPTION" in upper_message or "❌" in message:
            return logging.ERROR
        if "ERROR" in upper_message or "FAILED" in upper_message or "FAILURE" in upper_message:
            return logging.ERROR
        if "WARNING" in upper_message or "WARN" in upper_message or "⚠" in message:
            return logging.WARNING
        if "DEBUG" in upper_message:
            return logging.DEBUG
        return logging.INFO

    def _emit_line(self, logger_name: str, line: str, stacklevel: int) -> None:
        if not line:
            return

        clean_line = _sanitize_message(line)
        level = self._infer_log_level(clean_line)
        logger = logging.getLogger(logger_name)
        logger.log(level, clean_line, stacklevel=stacklevel)

    def write(self, message):
        if not message:
            return 0

        if isinstance(message, bytes):
            message = message.decode("utf-8", errors="replace")
        elif not isinstance(message, str):
            message = str(message)

        message = _ANSI_ESCAPE_PATTERN.sub("", message)
        state = self._get_local_state()

        if message.strip():
            state.logger_name = self._resolve_caller_logger_name()

        state.buffer += message
        written = len(message)

        while "\n" in state.buffer:
            line, state.buffer = state.buffer.split("\n", 1)
            line = line.rstrip()
            if line:
                self._emit_line(state.logger_name, line, stacklevel=3)

        return written

    def flush(self):
        state = self._get_local_state()
        if state.buffer:
            line = state.buffer.rstrip()
            if line:
                self._emit_line(state.logger_name, line, stacklevel=3)
            state.buffer = ""

    def isatty(self):
        return False


class SanitizeLogRecordFilter(logging.Filter):
    """Sanitize and normalize log records before writing."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        message = _ANSI_ESCAPE_PATTERN.sub("", message)
        message = _sanitize_message(message)
        record.msg = message

        if record.exc_text:
            exc_text = _ANSI_ESCAPE_PATTERN.sub("", record.exc_text)
            record.exc_text = _sanitize_message(exc_text)
            record.exc_info = None
        elif record.exc_info:
            exc_text = logging.Formatter().formatException(record.exc_info)
            exc_text = _ANSI_ESCAPE_PATTERN.sub("", exc_text)
            record.exc_text = _sanitize_message(exc_text)
            record.exc_info = None

        if record.stack_info:
            stack_info = _ANSI_ESCAPE_PATTERN.sub("", record.stack_info)
            record.stack_info = _sanitize_message(stack_info)

        record.args = ()
        return True

def _parse_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(value: Optional[str], default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_log_file_path() -> Path:
    """Resolve the backend log file path."""
    configured_path = os.environ.get("DRAGONCP_LOG_FILE", "").strip()
    if configured_path:
        candidate = Path(configured_path)
        if not candidate.is_absolute():
            candidate = PROJECT_ROOT / candidate
        return candidate

    return DEFAULT_LOG_DIR / DEFAULT_LOG_FILE_NAME


def _sanitize_message(message: str) -> str:
    sanitized = message

    for marker in _SENSITIVE_MARKERS:
        pattern = re.compile(rf"(?i)\b([A-Z0-9_]*{marker}[A-Z0-9_]*)\b(\s*[:=]\s*)(.+)$")
        match = pattern.search(sanitized)
        if match:
            sanitized = f"{match.group(1)}{match.group(2)}<redacted>"
            break

    sanitized = _AUTH_HEADER_PATTERN.sub(r"\1<redacted>", sanitized)
    sanitized = _BEARER_TOKEN_PATTERN.sub(r"\1<redacted>", sanitized)
    return sanitized


def _install_exception_hooks() -> None:
    def _handle_uncaught_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            _ORIGINAL_EXCEPTHOOK(exc_type, exc_value, exc_traceback)
            return
        logging.getLogger("dragoncp.crash").critical(
            "Unhandled exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    def _handle_thread_exception(args):
        thread_name = args.thread.name if args.thread else "unknown"
        logging.getLogger("dragoncp.crash").critical(
            "Unhandled exception in thread %s",
            thread_name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _handle_uncaught_exception
    threading.excepthook = _handle_thread_exception


def _redirect_std_streams() -> None:
    global _STD_STREAMS_REDIRECTED

    if _parse_bool(os.environ.get("DRAGONCP_REDIRECT_STD_STREAMS", "1"), default=True):
        sys.stdout = StreamToLogger("dragoncp.stdout", logging.INFO)
        sys.stderr = StreamToLogger("dragoncp.stderr", logging.ERROR)
        _STD_STREAMS_REDIRECTED = True


def shutdown_logging() -> None:
    """Flush and stop async logging listener."""
    global _LOGGING_CONFIGURED, _LOG_QUEUE_LISTENER, _LOG_QUEUE_HANDLER, _STD_STREAMS_REDIRECTED

    root_logger = logging.getLogger()

    if _LOG_QUEUE_LISTENER is not None:
        listener = _LOG_QUEUE_LISTENER
        _LOG_QUEUE_LISTENER = None

        listener.stop()
        listener_thread = getattr(listener, "_thread", None)
        if listener_thread is not None and listener_thread.is_alive():
            listener_thread.join(timeout=1.0)

    if _LOG_QUEUE_HANDLER is not None:
        if _LOG_QUEUE_HANDLER in root_logger.handlers:
            root_logger.removeHandler(_LOG_QUEUE_HANDLER)
        _LOG_QUEUE_HANDLER.close()
        _LOG_QUEUE_HANDLER = None

    if _STD_STREAMS_REDIRECTED:
        if isinstance(sys.stdout, StreamToLogger):
            sys.stdout.flush()
            sys.stdout = _ORIGINAL_STDOUT
        if isinstance(sys.stderr, StreamToLogger):
            sys.stderr.flush()
            sys.stderr = _ORIGINAL_STDERR
        _STD_STREAMS_REDIRECTED = False

    sys.excepthook = _ORIGINAL_EXCEPTHOOK
    threading.excepthook = _ORIGINAL_THREAD_EXCEPTHOOK
    _LOGGING_CONFIGURED = False


def _register_atexit_once() -> None:
    global _ATEXIT_REGISTERED

    if _ATEXIT_REGISTERED:
        return

    atexit.register(shutdown_logging)
    _ATEXIT_REGISTERED = True


def configure_logging() -> Path:
    """Configure global backend logging once for the process."""
    global _LOGGING_CONFIGURED, _LOG_QUEUE_LISTENER, _LOG_QUEUE_HANDLER

    if _LOGGING_CONFIGURED:
        return get_log_file_path()

    log_file_path = get_log_file_path()
    log_file_path.parent.mkdir(parents=True, exist_ok=True)

    log_level_name = os.environ.get("LOG_LEVEL", "INFO").upper().strip()
    log_level = getattr(logging, log_level_name, logging.INFO)

    max_bytes = _parse_int(os.environ.get("LOG_MAX_BYTES"), 20 * 1024 * 1024)
    backup_count = _parse_int(os.environ.get("LOG_BACKUP_COUNT"), 10)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(process)d | %(threadName)s | %(name)s | %(module)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        filename=log_file_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(SanitizeLogRecordFilter())

    handlers: list[logging.Handler] = [file_handler]

    if _parse_bool(os.environ.get("LOG_TO_CONSOLE", "1"), default=True):
        console_handler = logging.StreamHandler(stream=sys.__stdout__)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(SanitizeLogRecordFilter())
        handlers.append(console_handler)

    log_queue: queue.Queue = queue.Queue(-1)
    queue_handler = QueueHandler(log_queue)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(log_level)
    root_logger.addHandler(queue_handler)
    root_logger.propagate = False
    queue_handler.addFilter(SanitizeLogRecordFilter())
    _LOG_QUEUE_HANDLER = queue_handler

    _LOG_QUEUE_LISTENER = QueueListener(log_queue, *handlers, respect_handler_level=True)
    _LOG_QUEUE_LISTENER.start()

    logging.captureWarnings(True)
    _install_exception_hooks()
    _redirect_std_streams()

    _LOGGING_CONFIGURED = True
    _register_atexit_once()

    logging.getLogger("dragoncp.logging").info(
        "Logging configured at %s (level=%s)",
        log_file_path,
        logging.getLevelName(log_level),
    )

    return log_file_path
