"""
Cross-platform logger setup.

Usage:
    # Initialize logging once from the main application:
    from utils import logger as logger_utils
    logger = logger_utils.init_logger(log_file="logs/topstep_bot.log", level="INFO")
    # In other modules, get a module-specific logger:
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

def init_logger(log_file: str = None, level=logging.INFO):
    """
    Initialize the root logger with console output (and optional file output).
    If log_file is provided, logs will be written to that file (in addition to console).
    The level can be a logging level (int or str name). Returns the root logger.
    """
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    if root.handlers:
        # Already initialized, do nothing
        return root
    root.setLevel(level)
    # Console handler
    root.addHandler(_build_handler(sys.stdout, level))
    # File handler (use custom path if provided, else default logs/bot.log)
    if log_file:
        log_path = Path(log_file)
        if not log_path.is_absolute():
            base_dir = Path(__file__).resolve().parents[2]
            log_path = base_dir / log_file
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_stream = open(log_path, "a", encoding="utf-8", newline="")
        root.addHandler(_build_handler(file_stream, level))
    else:
        file_stream = open(_LOG_DIR / "bot.log", "a", encoding="utf-8", newline="")
        root.addHandler(_build_handler(file_stream, level))
    root.debug("Root logger initialised.")
    return root

def get_logger(name: str):
    """
    Get a logger with the given name, ensuring the root logger is initialized.
    """
    init_logger()
    return logging.getLogger(name)
