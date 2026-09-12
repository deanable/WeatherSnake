import logging
import os
import sys
from logging.handlers import RotatingFileHandler


def _log_path() -> str:
	"""Log file location.

	Frozen (PyInstaller) builds log to the user's application-data directory
	because the bundled source directory is a temp extraction dir; source runs
	log next to the source.
	"""
	if getattr(sys, "frozen", False):
		base = os.environ.get("APPDATA") or os.path.expanduser("~")
		return os.path.join(base, "WeatherSnake", "weathersnake.log")
	return os.path.join(os.path.dirname(os.path.abspath(__file__)), "weathersnake.log")


LOG_FILE = _log_path()


def setup_logging():
	"""Configure file-only logging with rotation. Call once at application startup."""
	root_logger = logging.getLogger()
	if root_logger.handlers:
		return  # Already configured

	os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

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
