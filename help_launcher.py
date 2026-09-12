"""Cross-platform help launcher for WeatherSnake.

Opens the compiled help (WeatherSnake.chm) with context-sensitive topic
resolution:

  * Windows: the native HTML Help viewer via the HTMLHelp API through ctypes
    (HH_HELP_CONTEXT with the widget's help context id, honouring the
    HelpFile option in the .hhp's [WINDOWS] block).
  * Other platforms / missing CHM: the packaged HTML topics in the default
    browser, jumping straight to the right anchor/topic page.

Widgets register their context id via ``register_help(widget, ctx_id)``;
``show_context_help(widget)`` resolves the nearest registered ancestor when a
container has focus. The GUI binds F1, a Help menu, and a help "what's this"
mode on top of this module.
"""
import ctypes
import logging
import os
import sys
import webbrowser

logger = logging.getLogger(__name__)

APP_NAME = "WeatherSnake"
CHM_NAME = "WeatherSnake.chm"
DEFAULT_CONTEXT_ID = 1000  # welcome

# Context ids (keep in sync with build_chm.TOPIC_IDS and the .hhp [MAP]).
TOPIC_IDS = {
	"welcome": 1000,
	"getting-started": 1001,
	"interface": 1002,
	"location": 1003,
	"periods": 1004,
	"depth": 1005,
	"units": 1006,
	"monthly": 1007,
	"precipitation": 1008,
	"conditions": 1009,
	"insights": 1010,
	"yearly": 1011,
	"comparison": 1012,
	"exports": 1013,
	"keyboard": 1014,
	"cli": 1015,
	"data": 1016,
	"troubleshooting": 1017,
	"about": 1018,
}

HTML_HELP_APP = 0  # lpstrFile: .chm path
HTML_HELP_TOPIC = 0x0000  # extra: "topic.htm>main"
HTML_HELP_CONTEXT = 0x0005  # extra: context id (DWORD)
HH_DISPLAY_TOPIC = 0x0000
HH_HELP_CONTEXT = 0x000F
HH_CLOSE_ALL = 0x001A

_HHCTRL_PATHS = [
	"C:\\Windows\\System32\\hhctrl.ocx",
	"C:\\Windows\\SysWOW64\\hhctrl.ocx",
]


def resource_dir():
	"""Directory containing the packaged help resources.

	Frozen PyInstaller builds unpack datas to sys._MEIPASS; source runs use the
	repo layout (help/ next to this file, or dist/help when compiled in place).
	"""
	if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
		base = sys._MEIPASS
	else:
		base = os.path.dirname(os.path.abspath(__file__))
	for candidate in (
		os.path.join(base, "help"),            # source layout
		os.path.join(base, "help", "html"),    # alternate layout
		os.path.join(base, "html"),            # dist layout (chm+html copied flat)
	):
		if os.path.isdir(candidate):
			return candidate
	return os.path.join(base, "help")


def chm_path():
	"""Full path to the bundled .chm, or None when it isn't present."""
	chm = None
	if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
		chm = os.path.join(sys._MEIPASS, CHM_NAME)
	else:
		chm = os.path.join(os.path.dirname(os.path.abspath(__file__)), "help", "html", CHM_NAME)
	if chm and os.path.isfile(chm):
		return chm
	return None


def _hhctrl():
	"""Load hhctrl.ocx and return its HtmlHelpW entry point, or None."""
	if os.name != "nt":
		return None
	for path in _HHCTRL_PATHS:
		if not os.path.isfile(path):
			continue
		try:
			lib = ctypes.WinDLL(path)
			fn = getattr(lib, "HtmlHelpW", None)
			if fn:
				fn.restype = ctypes.c_void_p
				fn.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p]
				return fn
		except OSError:
			continue
	return None


def _win_notify_hwnd():
	"""A hidden owner window is unnecessary; HH uses the desktop for TOPIC/CONTEXT."""
	return None


def open_chm(path, context_id=None):
	"""Open the CHM via hhctrl.ocx. Returns True on success."""
	fn = _hhctrl()
	if not fn:
		return False
	try:
		if context_id is None:
			data = None
			cmd = HH_DISPLAY_TOPIC
		else:
			# HH_HELP_CONTEXT expects the context id as a DWORD ptr arg
			data = ctypes.c_ulong(context_id)
			cmd = HH_HELP_CONTEXT
		fn(_win_notify_hwnd(), path, cmd, ctypes.cast(
			ctypes.byref(data) if data is not None else None, ctypes.c_void_p))
		logger.info("CHM opened: %s (context %s)", path, context_id)
		return True
	except Exception:
		logger.warning("CHM open failed for %s (context %s)", path, context_id, exc_info=True)
		return False


DEFAULT_TOPIC_FILE = "welcome.html"


def _html_topic_url(topic_name):
	"""Browser fallback URL for a topic page next to the .chm."""
	base = resource_dir()
	page = os.path.join(base, "html", topic_name)
	if not os.path.isfile(page):
		page = os.path.join(base, topic_name)
	return "file://" + page.replace("\\", "/")


def show_help(context_id=None):
	"""Open help at a context id (or the default topic when None).

	Uses the native CHM viewer on Windows; falls back to the browser with the
	same topic page elsewhere. Returns the display string used for logging.
	"""
	logger.info("show_help(context_id=%s)", context_id)
	chm = chm_path()
	if chm and os.name == "nt":
		if open_chm(chm, context_id):
			return "chm"
		logger.warning("CHM open failed; falling back to browser")
	# Browser fallback (macOS/Linux, or CHM missing on Windows)
	url = _html_topic_url(_topic_file(context_id))
	try:
		webbrowser.open(url)
		logger.info("Opened help in browser: %s", url)
	except Exception:
		logger.warning("Could not open browser for %s", url, exc_info=True)
	return "browser"


def _topic_file(context_id):
	"""Topic file for a context id, via build_chm.TOPIC_IDS."""
	if context_id is None:
		return DEFAULT_TOPIC_FILE
	try:
		from build_chm import TOPIC_IDS as BUILD_TOPICS
		return BUILD_TOPICS.get(int(context_id), DEFAULT_TOPIC_FILE)
	except (TypeError, ValueError, ImportError):
		return DEFAULT_TOPIC_FILE


def show_topic(topic_key):
	"""Open help by topic key (e.g. 'troubleshooting', 'cli', 'about')."""
	ctx = TOPIC_IDS.get(topic_key)
	return show_help(ctx)


class HelpRegistry:
	"""Per-widget context-id registry with nearest-ancestor resolution."""

	def __init__(self):
		self._topics = {}

	def register(self, widget, context_id):
		"""Register a widget's context id; replaces any previous one."""
		try:
			self._topics[widget] = int(context_id)
		except (TypeError, ValueError):
			logger.warning("register_help: bad context id %r", context_id)

	def lookup(self, widget):
		"""Resolve a widget's context id, walking up the widget tree."""
		seen = 0
		w = widget
		while w is not None and seen < 25:
			ctx = self._topics.get(w)
			if ctx is not None:
				return ctx
			try:
				w = w.master
			except AttributeError:
				break
			seen += 1
		return DEFAULT_CONTEXT_ID


registry = HelpRegistry()


def register_help(widget, context_id):
	"""Register a widget (or container) with a help context id."""
	registry.register(widget, context_id)


def show_context_help(widget):
	"""F1 handler: resolve the widget's context and open help there."""
	ctx = registry.lookup(widget)
	logger.debug("F1 on %r resolved to context id %s", widget, ctx)
	return show_help(ctx)


def close_all():
	"""Best-effort close of any open CHM windows (Windows only)."""
	fn = _hhctrl()
	if fn:
		try:
			fn(None, None, HH_CLOSE_ALL, None)
		except Exception:
			logger.debug("close_all failed", exc_info=True)
