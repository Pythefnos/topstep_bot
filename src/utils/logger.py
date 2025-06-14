"""
Cross-platform logger setup.

Usage:
    from utils.logger import get_logger
    log = get_logger(__name__)
"""
from pathlib import Path
import logging
import sys

_LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
_LOG_DIR.mkdir(exist_ok=True)

def _build_handler(stream, level):
    handler = logging.StreamHandler(stream)
    handler.setLevel(level)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        "%Y-%m-%d %H:%M:%S"
    )
    handler.setFormatter(fmt)
    return handler

def init_root(level=logging.INFO):
    """Idempotent root-logger init—safe to call many times."""
    root = logging.getLogger()
    if root.handlers:          # already initialised
        return root
    root.setLevel(level)
    root.addHandler(_build_handler(sys.stdout, level))
    file_handler = _build_handler(
        open(_LOG_DIR / "bot.log", "a", encoding="utf-8", newline=""),
        level
    )
    root.addHandler(file_handler)
    root.debug("Root logger initialised.")
    return root

def get_logger(name: str):
    init_root()
    return logging.getLogger(name)
