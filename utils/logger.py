"""
utils/logger.py
---------------
Centralized logging setup for the Offline AI Voice Clone application.

Provides a factory function `setup_logger()` that returns a configured
logging.Logger instance writing to both the console (color-coded) and
a rotating file at logs/app.log.

Usage:
    from utils.logger import setup_logger
    log = setup_logger(__name__)
    log.info("Model loaded successfully")
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ── Try to import colorlog; fall back to plain formatting ────────────────────
try:
    import colorlog  # type: ignore
    _HAS_COLORLOG = True
except ImportError:
    _HAS_COLORLOG = False


# ── Constants ────────────────────────────────────────────────────────────────
LOG_DIR: Path = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE: Path = LOG_DIR / "app.log"
MAX_BYTES: int = 5 * 1024 * 1024   # 5 MB per log file
BACKUP_COUNT: int = 3               # Keep 3 rotated files
DEFAULT_LEVEL: int = logging.DEBUG

# Console format (used when colorlog is not available)
PLAIN_FORMAT: str = (
    "%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s"
)
DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"

# Color map for colorlog
_LOG_COLORS: dict[str, str] = {
    "DEBUG":    "cyan",
    "INFO":     "green",
    "WARNING":  "yellow",
    "ERROR":    "red",
    "CRITICAL": "bold_red",
}


def _ensure_log_dir() -> None:
    """Create the logs/ directory if it does not already exist."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def _build_console_handler(level: int) -> logging.Handler:
    """
    Build a StreamHandler that writes to stderr.
    Uses colorlog if available, otherwise plain text formatting.
    """
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setLevel(level)

    if _HAS_COLORLOG:
        formatter = colorlog.ColoredFormatter(
            fmt=(
                "%(log_color)s%(asctime)s | %(levelname)-8s%(reset)s"
                " | %(name)-25s | %(message)s"
            ),
            datefmt=DATE_FORMAT,
            log_colors=_LOG_COLORS,
            reset=True,
            style="%",
        )
    else:
        formatter = logging.Formatter(fmt=PLAIN_FORMAT, datefmt=DATE_FORMAT)

    handler.setFormatter(formatter)
    return handler


def _build_file_handler(level: int) -> logging.Handler:
    """
    Build a RotatingFileHandler writing to logs/app.log.
    Plain text only (no ANSI escape codes in files).
    """
    _ensure_log_dir()
    handler = RotatingFileHandler(
        filename=str(LOG_FILE),
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(level)
    formatter = logging.Formatter(fmt=PLAIN_FORMAT, datefmt=DATE_FORMAT)
    handler.setFormatter(formatter)
    return handler


def setup_logger(
    name: str,
    level: int = DEFAULT_LEVEL,
    console: bool = True,
    file: bool = True,
) -> logging.Logger:
    """
    Create or retrieve a named logger with console and/or file handlers.

    Args:
        name:    Logger name — use __name__ in the calling module.
        level:   Minimum log level (default: DEBUG).
        console: Whether to attach a console (stderr) handler.
        file:    Whether to attach a rotating file handler.

    Returns:
        A configured logging.Logger instance.
    """
    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers if the logger was already configured
    if logger.handlers:
        return logger

    logger.setLevel(level)
    logger.propagate = False  # Prevent double-logging via root logger

    if console:
        logger.addHandler(_build_console_handler(level))

    if file:
        try:
            logger.addHandler(_build_file_handler(level))
        except PermissionError:
            # If we can't write to the log file, just continue with console
            logger.warning("Could not open log file — file logging disabled.")

    return logger


# ── Module-level logger for this file itself ─────────────────────────────────
_log = setup_logger(__name__)
_log.debug("Logger module initialised (colorlog=%s)", _HAS_COLORLOG)
