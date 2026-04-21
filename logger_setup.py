import logging
import os
from logging.handlers import RotatingFileHandler

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weathersnake.log")

def setup_logging():
    """Configure file-only logging with rotation. Call once at application startup."""
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return  # Already configured

    root_logger.setLevel(logging.DEBUG)

    handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setLevel(logging.DEBUG)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handler.setFormatter(formatter)

    root_logger.addHandler(handler)

    # Silence noisy third-party loggers
    for name in ("matplotlib", "PIL", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)
