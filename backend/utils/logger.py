"""
utils/logger.py
===============
Configures a structured logger for the Smart Nile backend.

Features
--------
- Rotating file handler  → data/logs/smartnile_YYYY-MM-DD.log
- Colour-coded console handler with sensor-name prefix
- Single call to get_logger() from any module

Usage
-----
    from utils.logger import get_logger
    log = get_logger(__name__)
    log.info("Sensor reading OK")
    log.warning("pH above threshold")
    log.error("Firebase write failed", exc_info=True)
"""

import logging
import logging.handlers
import sys
from datetime import date
from pathlib import Path


# ANSI colour codes — silent on Windows/non-TTY
_RESET  = "\033[0m"
_GREY   = "\033[90m"
_CYAN   = "\033[96m"
_YELLOW = "\033[93m"
_RED    = "\033[91m"
_BOLD   = "\033[1m"

_LEVEL_COLOURS = {
    logging.DEBUG:    _GREY,
    logging.INFO:     _CYAN,
    logging.WARNING:  _YELLOW,
    logging.ERROR:    _RED,
    logging.CRITICAL: _BOLD + _RED,
}


class _ColourFormatter(logging.Formatter):
    """Adds level-specific colour to console output."""

    FMT = "%(asctime)s [%(levelname)-8s] %(name)-20s  %(message)s"
    DATE = "%H:%M:%S"

    def format(self, record: logging.LogRecord) -> str:
        colour = _LEVEL_COLOURS.get(record.levelno, _RESET)
        use_colour = sys.stdout.isatty()
        prefix = colour if use_colour else ""
        suffix = _RESET if use_colour else ""
        formatter = logging.Formatter(
            fmt=f"{prefix}{self.FMT}{suffix}",
            datefmt=self.DATE,
        )
        return formatter.format(record)


def _build_file_handler(logs_dir: str) -> logging.Handler:
    Path(logs_dir).mkdir(parents=True, exist_ok=True)
    log_path = Path(logs_dir) / f"smartnile_{date.today()}.log"
    handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,   # 5 MB per file
        backupCount=14,              # keep 14 days of rotated logs
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(name)-20s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    return handler


_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(_ColourFormatter())

_root_configured = False


def configure_logging(level: str = "INFO", logs_dir: str = "data/logs") -> None:
    """
    Call once at startup (main.py does this).
    Subsequent calls are no-ops.
    """
    global _root_configured
    if _root_configured:
        return
    numeric = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(numeric)
    root.addHandler(_console_handler)
    root.addHandler(_build_file_handler(logs_dir))
    # silence noisy third-party loggers
    for noisy in ("urllib3", "firebase_admin", "google", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _root_configured = True


def get_logger(name: str) -> logging.Logger:
    """
    Return a named logger.  configure_logging() should have been called
    before the first get_logger() call, but this is safe either way.
    """
    return logging.getLogger(name)
