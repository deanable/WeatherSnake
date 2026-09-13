"""WeatherSnake GUI — Wizard-style multi-step interface.

Visual identity:
  Palette: deep ocean ink (#1A2332), warm/cool temperature tones (#E67E22 / #3B82F6),
  precipitation blue (#60A5FA), near-white workspace (#F8FAFC).
  Typography: Inter → Segoe UI → Helvetica (first family present on the system);
  JetBrains Mono → Consolas for tabular numbers. All lookups happen at startup.
  Signature: a temperature range bar that maps the analysed min/max onto a
  fixed -15 °C … +40 °C blue→orange gradient while data loads.

Layout: 4-step wizard (Location → Time → Weather Options → Output) with a
left step sidebar, an app bar (logo · version · Settings · ?) and a bottom
status bar; each step screen shows an eyebrow/title/blurb header plus a
progress strip, and the Output step reveals the results panels (data table,
chart, insights) and export buttons after fetching.
"""

import logging
import re
import sys
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import threading
import json
import os
import webbrowser
from datetime import datetime

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from logger_setup import setup_logging
from version import APP_NAME, VERSION
from help_launcher import (
    TOPIC_IDS, close_all, register_help, show_context_help, show_topic,
)
from api_client import get_coordinates, fetch_historical_weather
from processing import process_weather_data, custom_range_days, get_season_months
from output import create_visualization_figure, export_to_csv, build_insights_text
from chart_theme import PALETTE

logger = logging.getLogger(__name__)

# Single shared palette (GUI chrome + charts) — see chart_theme.py.
C = PALETTE

# ── Help context ids ────────────────────────────────────────────────────
CTX = {
    "root": TOPIC_IDS["welcome"],
    "location": TOPIC_IDS["location"],
    "period": TOPIC_IDS["periods"],
    "depth": TOPIC_IDS["depth"],
    "units": TOPIC_IDS["units"],
    "monthly": TOPIC_IDS["monthly"],
    "unify": TOPIC_IDS["monthly"],
    "precip_threshold": TOPIC_IDS["precipitation"],
    "insights": TOPIC_IDS["insights"],
    "yearly": TOPIC_IDS["yearly"],
    "fetch": TOPIC_IDS["getting-started"],
    "save": TOPIC_IDS["exports"],
    "export_csv": TOPIC_IDS["exports"],
    "chart_export": TOPIC_IDS["exports"],
    "chart_token": TOPIC_IDS["exports"],
    "quickchart": TOPIC_IDS["exports"],
    "results": TOPIC_IDS["interface"],
}


def _settings_path() -> str:
    """Settings file location — frozen builds use APPDATA, source keeps local."""
    if getattr(sys, "frozen", False):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "WeatherSnake", "ui_settings.json")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui_settings.json")


SETTINGS_FILE = _settings_path()


# ── Datawrapper API token persistence (OS keychain / registry) ──────────────
try:
    import winreg

    _REG_PATH = "SOFTWARE\\WeatherSnake"
    _REG_VALUE = "DatawrapperToken"


    def _write_api_token(token: str) -> None:
        """Persist the Datawrapper token under HKCU so the user is not prompted again."""
        try:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, _REG_PATH)
            winreg.SetValueEx(key, _REG_VALUE, 0, winreg.REG_SZ, token)
            winreg.CloseKey(key)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not write Datawrapper token to registry: %s", exc)


    def _read_api_token() -> str:
        """Return the stored Datawrapper token, or an empty string."""
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH)
            value, _ = winreg.QueryValueEx(key, _REG_VALUE)
            winreg.CloseKey(key)
            return value or ""
        except FileNotFoundError:
            return ""
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not read Datawrapper token from registry: %s", exc)
            return ""


    def _open_api_key_site() -> None:
        """Open the Datawrapper settings page in the default browser."""
        webbrowser.open("https://app.datawrapper.de/settings/account")


except ImportError:
    # macOS / non-Windows: prefer the OS keychain (macOS Keychain / Linux
    # Secret Service) via `keyring`, falling back to a private dotfile.
    import base64
    import json

    _TOKEN_PATH = os.path.join(
        os.path.expanduser("~"), ".weathersnake", "datawrapper_token.json"
    )

    try:
        import keyring as _keyring

        _KEYCHAIN = _keyring
    except Exception:  # noqa: BLE001  (missing package or broken backend)
        _KEYCHAIN = None


    def _write_api_token(token: str) -> None:
        """Persist the Datawrapper token in the OS keychain or a dotfile."""
        wrote = False
        if _KEYCHAIN is not None:
            try:
                _KEYCHAIN.set_password("WeatherSnake", "DatawrapperToken", token)
                wrote = True
            except Exception as exc:  # noqa: BLE001
                logger.debug("Keychain write failed; using dotfile: %s", exc)
        if not wrote:
            try:
                os.makedirs(os.path.dirname(_TOKEN_PATH), exist_ok=True)
                payload = {
                    "token": base64.b64encode(token.encode("utf-8")).decode("ascii"),
                    "created": datetime.now().isoformat(),
                }
                with open(_TOKEN_PATH, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, indent=2)
                logger.debug("Wrote Datawrapper token to %s", _TOKEN_PATH)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Could not write Datawrapper token to disk: %s", exc)


    def _read_api_token() -> str:
        """Return the stored Datawrapper token, or an empty string."""
        if _KEYCHAIN is not None:
            try:
                value = _KEYCHAIN.get_password("WeatherSnake", "DatawrapperToken")
                if value:
                    return value
            except Exception as exc:  # noqa: BLE001
                logger.debug("Keychain read failed; trying dotfile: %s", exc)
        try:
            with open(_TOKEN_PATH, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return base64.b64decode(payload["token"].encode("ascii")).decode("utf-8") or ""
        except FileNotFoundError:
            return ""
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not read Datawrapper token from disk: %s", exc)
            return ""


    def _open_api_key_site() -> None:
        """Open the Datawrapper settings page in the default browser."""
        webbrowser.open("https://app.datawrapper.de/settings/account")


# ══════════════════════════════════════════════════════════════════════════
#  Wizard step definitions
# ══════════════════════════════════════════════════════════════════════════
WIZARD_STEPS = [
    {"title": "Location", "subtitle": "Where are you analysing?",
     "blurb": "Select a preset location or enter custom coordinates."},
    {"title": "Time Period", "subtitle": "When do you want data for?",
     "blurb": "Choose a season, full year, month, or custom date range."},
    {"title": "Weather Options", "subtitle": "Customise your analysis",
     "blurb": "Choose which metrics and reports to generate."},
    {"title": "Output", "subtitle": "Review and export your results",
     "blurb": "Fetch data to generate the chart and analysis."},
]


class WizardProgress(tk.Canvas):
    """Horizontal step progress indicator for the wizard.

    Shows numbered circles connected by lines; completed steps are filled,
    the current step has a pulsing ring, future steps are muted.
    """

    _HEIGHT = 70

    def __init__(self, parent, **kw):
        super().__init__(parent, height=self._HEIGHT, bg=C["bg_light"],
                         highlightthickness=0)
        self._current_step = 0
        self._completed_steps = set()
        self._pulse = 0.0
        self._after_id = None

    def set_step(self, step, completed=()):
        """Update which step is active and which are completed."""
        self._current_step = step
        self._completed_steps = set(completed)
        self._draw()

    def start_pulse(self):
        self._pulse = 0.0
        self._schedule(600)

    def stop_pulse(self):
        if self._after_id:
            self.after_cancel(self._after_id)
            self._after_id = None

    def _schedule(self, delay_ms):
        if self._after_id:
            self.after_cancel(self._after_id)
        self._after_id = self.after(delay_ms, self._pulse_draw)

    def _pulse_draw(self):
        self._after_id = None
        self._pulse = (self._pulse + 1) % 4
        self._draw()
        if self._pulse > 0:
            self._schedule(600)

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 200:
            return

        n = len(WIZARD_STEPS)
        circle_r = 16
        total_w = n * 2 * circle_r + (n - 1) * 30
        gap = max(30, (w - 40 - total_w) // (n - 1)) if n > 1 else 0
        start_x = (w - (total_w + (n - 1) * gap)) // 2

        for i, step in enumerate(WIZARD_STEPS):
            cx = start_x + i * (2 * circle_r + gap) + circle_r
            cy = h // 2 - 4

            # Connector line between steps
            if i > 0:
                prev_cx = start_x + (i - 1) * (2 * circle_r + gap) + 2 * circle_r + gap // 2
                if i - 1 in self._completed_steps:
                    line_color = C["temp_warm"]
                else:
                    line_color = C["divider"]
                self.create_line(prev_cx - circle_r // 2, cy,
                                 cx - circle_r - circle_r // 2, cy,
                                 fill=line_color, width=2)

            # Circle
            if i in self._completed_steps:
                fill_color = C["temp_warm"]
                text_color = "#FFFFFF"
                check = "\u2713"  # checkmark
            elif i == self._current_step:
                fill_color = C["surface"]
                text_color = C["deep_ocean"]
                check = str(i + 1)
                # Pulsing ring
                pulse_r = circle_r + 4 + (3 if self._pulse % 2 == 0 else 0)
                self.create_oval(cx - pulse_r, cy - pulse_r,
                                 cx + pulse_r, cy + pulse_r,
                                 outline=C["temp_warm"], width=2)
            else:
                fill_color = C["input_bg"]
                text_color = C["text_muted"]
                check = str(i + 1)

            self.create_oval(cx - circle_r, cy - circle_r,
                             cx + circle_r, cy + circle_r,
                             fill=fill_color, outline=C["divider"], width=1)
            self.create_text(cx, cy, text=check,
                             font=_UI_FONT(11, "bold"), fill=text_color)

            # Step label below
            label_y = cy + circle_r + 16
            if i <= self._current_step:
                lbl_color = C["text_primary"]
                lbl_weight = "bold"
            else:
                lbl_color = C["text_muted"]
                lbl_weight = "normal"
            self.create_text(cx, label_y, text=step["title"],
                             font=_UI_FONT(9, lbl_weight), fill=lbl_color)


# ══════════════════════════════════════════════════════════════════════════
#  Signature element — temperature range bar (weather-appropriate)
# ══════════════════════════════════════════════════════════════════════════
class TemperatureTimeline(tk.Canvas):
    """Temperature range bar shown while data loads, then the fetched range.

    A single blue→orange gradient bar represents the °C scale; the min/max of
    the analysed data are marked on it once known. While a fetch is running a
    subtle pulse animates (a few repaints per second, not per frame).
    """

    _HEIGHT = 34

    def __init__(self, parent, **kw):
        super().__init__(parent, height=self._HEIGHT, bg=C["bg_light"],
                         highlightthickness=0)
        self._running = False
        self._after_id = None
        self._pulse = 0.0
        self._min_temp = None
        self._max_temp = None

    def set_temperature_range(self, min_temp, max_temp):
        """Record the analysed min/max (°C-scale values from the engine)."""
        if min_temp is None or max_temp is None:
            return
        self._min_temp = float(min_temp)
        self._max_temp = float(max_temp)

    def start(self):
        self._running = True
        self._pulse = 0.0
        self._schedule(80)

    def stop(self):
        self._running = False
        if self._after_id:
            self.after_cancel(self._after_id)
            self._after_id = None

    def _schedule(self, delay_ms):
        if self._after_id:
            self.after_cancel(self._after_id)
        self._after_id = self.after(delay_ms, self._draw)

    @staticmethod
    def _temp_to_color(t):
        """Map a temperature (°C) onto the cool→warm gradient."""
        ratio = max(0.0, min(1.0, (t + 15.0) / 55.0))   # -15°C … +40°C
        c0, c1 = (59, 130, 246), (230, 126, 34)          # temp_cool → temp_warm
        r = int(c0[0] + (c1[0] - c0[0]) * ratio)
        g = int(c0[1] + (c1[1] - c0[1]) * ratio)
        b = int(c0[2] + (c1[2] - c0[2]) * ratio)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _draw(self):
        self._after_id = None
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 20 or h < 10:
            if self._running:
                self._schedule(120)
            return

        bar_y, bar_h = h // 2 - 4, 8
        pad = 60  # room for the min/max labels at the ends

        # Gradient bar: one rectangle per 4px segment keeps this cheap.
        seg_w = 4
        n = max(1, (w - 2 * pad) // seg_w)
        for i in range(n):
            t = -15.0 + 55.0 * i / max(1, n - 1)
            color = self._temp_to_color(t)
            x = pad + i * seg_w
            self.create_rectangle(x, bar_y, x + seg_w + 1, bar_y + bar_h,
                                  fill=color, outline="")

        # Labels on the fixed °C scale (the engine's native units).
        self.create_text(pad - 6, bar_y + bar_h // 2, text="-15°C",
                         font=_MONO_FONT(8), fill=C["text_muted"], anchor="e")
        self.create_text(pad + (w - 2 * pad) + 6, bar_y + bar_h // 2, text="+40°C",
                         font=_MONO_FONT(8), fill=C["text_muted"], anchor="w")

        # Mark the analysed range once known.
        if self._min_temp is not None and self._max_temp is not None:
            span = max(0.5, self._max_temp - self._min_temp)
            usable = w - 2 * pad
            x0 = pad + max(0.0, min(1.0, (self._min_temp + 15.0) / 55.0)) * usable
            x1 = pad + max(0.0, min(1.0, (self._max_temp + 15.0) / 55.0)) * usable
            if x1 - x0 < 6:
                x0, x1 = (x0 + x1) / 2 - 3, (x0 + x1) / 2 + 3
            self.create_rectangle(x0, bar_y - 3, x1, bar_y + bar_h + 3,
                                  outline=C["deep_ocean"], width=2)
            self.create_text(w - 8, bar_y + bar_h // 2,
                             text=f"{self._min_temp:.1f}°C … {self._max_temp:.1f}°C",
                             font=_MONO_FONT(8),
                             fill=C["text_secondary"], anchor="e")

        # Subtle pulse while a fetch is in progress (a few repaints per second).
        if self._running:
            self._pulse = (self._pulse + 1) % 4
            if self._pulse == 0:
                self.create_text(w // 2, bar_y - 8, text="analysing…",
                                 font=_UI_FONT(8),
                                 fill=C["text_muted"], anchor="center")
            self._schedule(240)


# ══════════════════════════════════════════════════════════════════════════
#  Styled ttk theme
# ══════════════════════════════════════════════════════════════════════════
# ── Fonts ─────────────────────────────────────────────────────────────────
# Prefer the modern faces from the design spec; silently fall back to fonts
# that ship with Windows/other OSes when they are not installed.
import tkinter.font as tkfont

_UI_FONT_NAME = "Segoe UI"
_MONO_FONT_NAME = "Consolas"


def _pick_font(preferred, fallbacks):
    """Return the first font family available on this system."""
    try:
        available = set(tkfont.families())
    except tk.TclError:
        return preferred
    for name in [preferred, *fallbacks]:
        if name in available:
            return name
    return "TkDefaultFont"


def _init_fonts(root):
    global _UI_FONT_NAME, _MONO_FONT_NAME
    _UI_FONT_NAME = _pick_font("Inter", ["Segoe UI", "Helvetica", "Arial"])
    _MONO_FONT_NAME = _pick_font("JetBrains Mono", ["Consolas", "Courier New", "Courier"])
    # Nudge the classic Tk option database so plain tk widgets match too.
    root.option_add("*Font", (_UI_FONT_NAME, 10))


def _UI_FONT(size, weight="normal"):
    return (_UI_FONT_NAME, size, weight)


def _MONO_FONT(size, weight="normal"):
    return (_MONO_FONT_NAME, size, weight)


def setup_styles(root):
    """Apply a custom ttk style that emphasizes weather data visualization."""
    _init_fonts(root)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=C["bg_light"], foreground=C["text_primary"],
                    font=(_UI_FONT_NAME, 10), bordercolor=C["divider"])

    # App bar buttons — small bordered pills (design '.app-bar .controls button')
    style.configure("AppBar.TButton", padding=(10, 3), font=(_UI_FONT_NAME, 9),
                    background=C["bg_light"], foreground=C["text_secondary"],
                    borderwidth=1, relief="solid")
    style.map("AppBar.TButton",
              background=[("active", C["surface"])],
              foreground=[("active", C["temp_cool"]),
                          ("!disabled", C["text_secondary"])])

    # LabelFrame - weather data sections
    style.configure("TLabelFrame", background=C["bg_light"], foreground=C["deep_ocean"],
                    font=(_UI_FONT_NAME, 10, "bold"), relief="flat", borderwidth=1)
    style.map("TLabelFrame",
              background=[("active", "#FFFFFF")],
              foreground=[("active", C["temp_warm"])])

    # Buttons — export/output row (design '.output-btn')
    style.configure("TButton", padding=(12, 6), font=(_UI_FONT_NAME, 9, "bold"),
                    background=C["surface"], foreground=C["text_secondary"],
                    borderwidth=1, relief="solid")
    style.map("TButton",
              background=[("active", C["hover"])],
              foreground=[("active", C["temp_cool"]),
                          ("disabled", C["text_muted"])])

    # Accent button variant — primary actions (design '.btn-next' / '.btn-fetch')
    style.configure("Accent.TButton", background=C["temp_warm"], foreground="#FFFFFF",
                    relief="flat", borderwidth=0, padding=(18, 8))
    style.map("Accent.TButton",
              background=[("active", "#D35400"), ("disabled", C["temp_warm"])],
              foreground=[("active", "#FFFFFF"), ("disabled", "#FFFFFF")])

    # Wizard navigation buttons (design '.btn-back')
    style.configure("Wizard.TButton", padding=(14, 8), font=(_UI_FONT_NAME, 9, "bold"),
                    background=C["surface"], foreground=C["text_secondary"],
                    borderwidth=1, relief="solid")
    style.map("Wizard.TButton",
              background=[("active", C["hover"])],
              foreground=[("active", C["temp_cool"]),
                          ("disabled", C["text_muted"])])

    # Checkbuttons - weather options
    style.configure("TCheckbutton", background=C["bg_light"], foreground=C["text_primary"],
                    font=(_UI_FONT_NAME, 9))

    # Combobox — data selection (design '.combobox')
    style.configure("TCombobox", fieldbackground=C["input_bg"], background=C["surface"],
                    arrowcolor=C["text_secondary"], relief="solid",
                    bordercolor=C["divider"], lightcolor=C["divider"],
                    darkcolor=C["divider"], borderwidth=1, padding=(8, 4))
    style.map("TCombobox",
              fieldbackground=[("readonly", C["input_bg"])],
              bordercolor=[("focus", C["temp_warm"])])

    # Entry / Spinbox — numeric inputs (design '.spinbox')
    style.configure("TSpinbox", fieldbackground=C["input_bg"], background=C["surface"],
                    relief="solid", bordercolor=C["divider"], padding=(8, 4))
    style.configure("TEntry", fieldbackground=C["input_bg"],
                    relief="solid", bordercolor=C["divider"], padding=(8, 4))

    # Treeview — weather data table (design '.table-scroll')
    style.configure("Treeview", background=C["surface"], foreground=C["text_primary"],
                    fieldbackground=C["surface"], font=(_MONO_FONT_NAME, 9),
                    rowheight=24, borderwidth=0, relief="flat")
    style.configure("Treeview.Heading", font=(_MONO_FONT_NAME, 8, "bold"),
                    background=C["bg_light"], foreground=C["text_muted"],
                    relief="flat", padding=(6, 6))
    style.map("Treeview.Heading", background=[("active", C["bg_light"])])
    style.map("Treeview",
              background=[("selected", C["precipitation"])],
              foreground=[("selected", "#FFFFFF")])

    # Scrollbars — slim, cool-blue thumb on a light trough
    style.configure("Vertical.TScrollbar", background=C["temp_cool"],
                    troughcolor=C["bg_light"], bordercolor=C["divider"],
                    arrowcolor=C["text_secondary"], relief="flat")


# ══════════════════════════════════════════════════════════════════════════
#  Tooltip
# ══════════════════════════════════════════════════════════════════════════
class Tooltip:
    """Simple tooltip for tkinter widgets."""

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tipwindow = None
        widget.bind("<Enter>", self.show_tip)
        widget.bind("<Leave>", self.hide_tip)

    def show_tip(self, event=None):
        if self.tipwindow or not self.text:
            return
        try:
            x, y, _, cy = self.widget.bbox("insert")
        except (tk.TclError, ValueError):
            # Some themed widgets (ttk.Entry, ttk.Combobox, …) don't support
            # bbox("insert") — fall back to the pointer position.
            x, y, cy = 0, 0, 0
        x = x + self.widget.winfo_rootx() + 25
        y = y + cy + self.widget.winfo_rooty() + 25
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, justify=tk.LEFT,
                         background="#FFFFFF", relief=tk.SOLID, borderwidth=1,
                         font=_UI_FONT(8), foreground=C["text_primary"])
        label.pack(ipadx=4, padx=4, pady=2)

    def hide_tip(self, event=None):
        tw = self.tipwindow
        self.tipwindow = None
        if tw:
            tw.destroy()


# ══════════════════════════════════════════════════════════════════════════
#  Main application with wizard layout
# ══════════════════════════════════════════════════════════════════════════
class WeatherJuiceApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} v{VERSION}")
        self.root.geometry("1280x780")
        self.root.minsize(1080, 660)
        self.root.configure(bg=C["bg_light"])
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        setup_styles(self.root)
        self.current_step = 0
        
        # Initialize month mappings BEFORE loading/apply settings
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        self._month_to_num = {name: i + 1 for i, name in enumerate(month_names)}
        self._last_days = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
                           7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}
        
        self.create_widgets()
        self.create_menu()
        self.load_settings()
        self.apply_settings()
        self.root.bind("<F1>", self.on_f1)
        self.root.bind("<Help>", self._help_event)
        self.root.bind("<Control-F1>", lambda e: show_topic("welcome"))
        self.root.bind("<Control-s>", lambda e: self.save_to_jpg())
        self.root.bind("<Control-e>", lambda e: self.export_csv())
        self.root.bind("<Control-r>", lambda e: self.fetch_data_thread())

    # ── Menu ──────────────────────────────────────────────────────────
    def create_menu(self):
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Fetch Data", command=self.fetch_data_thread,
                              accelerator="Ctrl+R")
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_closing)
        menubar.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Help Topics", command=lambda: show_topic("welcome"),
                              accelerator="F1")
        help_menu.add_command(label="Getting Started", command=lambda: show_topic("getting-started"))
        help_menu.add_command(label="Using the Window", command=lambda: show_topic("interface"))
        help_menu.add_separator()
        help_menu.add_command(label="CLI Reference", command=lambda: show_topic("cli"))
        help_menu.add_command(label="Data Sources and Accuracy", command=lambda: show_topic("data"))
        help_menu.add_separator()
        help_menu.add_command(label="Troubleshooting", command=lambda: show_topic("troubleshooting"))
        help_menu.add_command(label="Keyboard Shortcuts", command=lambda: show_topic("keyboard"))
        help_menu.add_separator()
        help_menu.add_command(label="About WeatherSnake", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.root.config(menu=menubar)
        self._help_menu = help_menu

    def show_about(self):
        messagebox.showinfo(
            "About WeatherSnake",
            f"{APP_NAME} v{VERSION}\n\n"
            "A historical weather analyzer: multi-year averages, most-common conditions, "
            "typical ranges and extremes, year-over-year trends, and recent-vs-baseline "
            "comparisons.\n\n"
            "Weather data provided by Open-Meteo (https://open-meteo.com/): "
            "ERA5/ERA5-Land reanalysis, Copernicus/ECMWF, CC BY 4.0.\n\n"
            "Released under the MIT License.",
            parent=self.root,
        )

    # ── F1 help ───────────────────────────────────────────────────────
    def on_f1(self, event=None):
        widget = self.root.focus_get()
        if widget is None:
            widget = self.root
        return show_context_help(widget)

    def _help_event(self, event):
        self.on_f1(event)
        return "break"

    # ── Design helpers (panels, option cards, step sidebar) ──────────
    def _panel(self, parent, title):
        """Design '.panel': bordered surface card with a small header strip."""
        outer = tk.Frame(parent, bg=C["surface"],
                         highlightbackground=C["divider"], highlightthickness=1)
        header = tk.Label(outer, text=title, bg=C["surface"], fg=C["text_secondary"],
                          font=_UI_FONT(9, "bold"), anchor="w", padx=14, pady=9)
        header.pack(side=tk.TOP, fill=tk.X)
        tk.Frame(outer, bg=C["divider"], height=1).pack(side=tk.TOP, fill=tk.X)
        body = tk.Frame(outer, bg=C["surface"])
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        return outer, body, header

    def _option_card_frame(self, parent):
        """Design '.checkbox-group .option': bordered light card row."""
        card = tk.Frame(parent, bg=C["bg_light"],
                        highlightbackground=C["divider"], highlightthickness=1)
        card.pack(side=tk.TOP, fill=tk.X, pady=2)
        return card

    def _option_card(self, parent, text, variable):
        """One option card containing a single checkbutton."""
        card = self._option_card_frame(parent)
        cb = ttk.Checkbutton(card, text=text, variable=variable)
        cb.pack(side=tk.LEFT, anchor="w", padx=10, pady=6)
        return cb

    def _build_sidebar(self, parent):
        """Left step navigation — clickable list of wizard steps."""
        sidebar = tk.Frame(parent, bg=C["surface"], width=200,
                           highlightbackground=C["divider"], highlightthickness=1)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)
        inner = tk.Frame(sidebar, bg=C["surface"])
        inner.pack(side=tk.TOP, fill=tk.X, padx=12, pady=20)

        self._sidebar_items = []
        for i, step_def in enumerate(WIZARD_STEPS):
            item = tk.Label(inner, text=f"{i + 1}.  {step_def['title']}",
                            bg=C["surface"], fg=C["text_secondary"],
                            font=_UI_FONT(9), anchor="w", padx=10, pady=8,
                            cursor="hand2")
            item.pack(side=tk.TOP, fill=tk.X, pady=2)
            item._step_index = i
            item.bind("<Button-1>", lambda _e, idx=i: self._go_step(idx))
            item.bind("<Enter>", self._sidebar_enter)
            item.bind("<Leave>", self._sidebar_leave)
            self._sidebar_items.append(item)

    def _sidebar_enter(self, event):
        item = event.widget
        if item._step_index != self.current_step:
            item.config(bg=C["hover"])

    def _sidebar_leave(self, event):
        item = event.widget
        if item._step_index != self.current_step:
            item.config(bg=C["surface"])

    def _paint_sidebar(self, current):
        """Highlight the active step; design '.step.current' = warm chip."""
        for item in self._sidebar_items:
            if item._step_index == current:
                item.config(bg=C["temp_warm"], fg="#FFFFFF", font=_UI_FONT(9, "bold"))
            else:
                item.config(bg=C["surface"], fg=C["text_secondary"], font=_UI_FONT(9))

    def _go_step(self, idx):
        """Sidebar navigation: jump straight to a step (validate forward jumps)."""
        if idx == self.current_step:
            return
        if idx > self.current_step and not self._validate_current_step():
            return
        self._show_step(idx)

    # ── Widgets ───────────────────────────────────────────────────────
    def create_widgets(self):
        # ── App bar (top chrome) ──────────────────────────────────────
        app_bar = tk.Frame(self.root, bg=C["surface"])
        app_bar.pack(side=tk.TOP, fill=tk.X)
        app_bar_inner = tk.Frame(app_bar, bg=C["surface"])
        app_bar_inner.pack(side=tk.TOP, fill=tk.X, padx=16, pady=10)

        tk.Label(app_bar_inner, text="WeatherSnake", bg=C["surface"],
                 fg=C["temp_warm"], font=_UI_FONT(12, "bold")).pack(side=tk.LEFT)
        tk.Label(app_bar_inner, text=f"v{VERSION}", bg=C["surface"],
                 fg=C["text_muted"], font=_MONO_FONT(8)).pack(side=tk.LEFT,
                                                              padx=(10, 0))

        help_btn = ttk.Button(app_bar_inner, text="?", style="AppBar.TButton", width=3,
                              command=self.on_f1)
        help_btn.pack(side=tk.RIGHT)
        Tooltip(help_btn, "Context help (F1).")

        settings_btn = ttk.Button(app_bar_inner, text="Settings", style="AppBar.TButton",
                                  command=lambda: self._go_step(2))
        settings_btn.pack(side=tk.RIGHT, padx=(0, 8))
        Tooltip(settings_btn, "Weather options, units and report settings (step 3).")

        # ── Status bar (bottom chrome) ─────────────────────────────────
        self.status_var = tk.StringVar(value="Ready.")
        self.status_context_var = tk.StringVar(value="Data: Open-Meteo · ERA5 · CC BY 4.0")
        status_bar = tk.Frame(self.root, bg=C["surface"])
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_label = tk.Label(status_bar, textvariable=self.status_var,
                                     fg=C["text_muted"], bg=C["surface"],
                                     font=_MONO_FONT(8), anchor="w")
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=16, pady=5)
        tk.Label(status_bar, textvariable=self.status_context_var,
                 fg=C["text_muted"], bg=C["surface"], font=_UI_FONT(8),
                 anchor="e").pack(side=tk.RIGHT, padx=16, pady=5)
        tk.Frame(self.root, bg=C["divider"], height=1).pack(side=tk.BOTTOM, fill=tk.X)

        # ── Wizard body: step sidebar + step content ──────────────────
        body = tk.Frame(self.root, bg=C["bg_light"])
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self._build_sidebar(body)

        content = tk.Frame(body, bg=C["bg_light"])
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=24, pady=12)

        # Step header: eyebrow, title, blurb
        self.eyebrow_label = tk.Label(content, text="", bg=C["bg_light"],
                                      fg=C["temp_warm"], font=_MONO_FONT(8, "bold"),
                                      anchor="w")
        self.eyebrow_label.pack(side=tk.TOP, fill=tk.X)
        self.step_title_label = tk.Label(content, text="", bg=C["bg_light"],
                                         fg=C["text_primary"], font=_UI_FONT(15, "bold"),
                                         anchor="w")
        self.step_title_label.pack(side=tk.TOP, fill=tk.X, pady=(2, 0))
        self.step_blurb_label = tk.Label(content, text="", bg=C["bg_light"],
                                         fg=C["text_muted"], font=_UI_FONT(9),
                                         anchor="w")
        self.step_blurb_label.pack(side=tk.TOP, fill=tk.X, pady=(2, 0))

        # Progress indicator
        self.progress = WizardProgress(content)
        self.progress.pack(side=tk.TOP, fill=tk.X, pady=(4, 0))
        self.progress.set_step(0)

        # Step content area
        self.step_frame = tk.Frame(content, bg=C["bg_light"])
        self.step_frame.pack(side=tk.TOP, fill=tk.X, pady=(8, 0))

        # Navigation buttons
        nav_frame = tk.Frame(content, bg=C["bg_light"])
        nav_frame.pack(side=tk.TOP, fill=tk.X, pady=(4, 0))

        self.back_btn = ttk.Button(nav_frame, text="Back", command=self._go_back,
                                    style="Wizard.TButton", state="disabled")
        self.back_btn.pack(side=tk.LEFT, padx=(0, 8))
        Tooltip(self.back_btn, "Go back to the previous step.")

        self.next_btn = ttk.Button(nav_frame, text="Next", command=self._go_next,
                                    style="Accent.TButton")
        self.next_btn.pack(side=tk.LEFT, padx=(0, 8))
        Tooltip(self.next_btn, "Continue to the next step.")

        self.fetch_btn = ttk.Button(nav_frame, text="Fetch Data", command=self.fetch_data_thread,
                                     style="Accent.TButton")
        # Don't pack initially - only show on the last step
        Tooltip(self.fetch_btn, "Retrieve weather data and generate the chart.")

        # Temperature timeline (transient — shown during fetch)
        self.timeline = TemperatureTimeline(content)

        # ── Results area (Output step, after a fetch) ─────────────────
        self.results_frame = tk.Frame(content, bg=C["bg_light"])

        # Left: data table panel
        table_panel, table_body, _ = self._panel(self.results_frame, "Data")
        table_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))
        table_panel.configure(width=320)
        table_panel.pack_propagate(False)

        columns = ("Date", "Max Temp", "Min Temp", "Precip")
        self.tree = ttk.Treeview(table_body, columns=columns, show="headings", height=16)
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=72, anchor=tk.CENTER)
        tree_scroll = ttk.Scrollbar(table_body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Right: analysis summary panel (sits beside the chart)
        self.conditions_frame, conditions_body, _ = self._panel(
            self.results_frame, "Analysis Summary")
        self.conditions_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        self.conditions_frame.configure(width=320)
        self.conditions_frame.pack_propagate(False)
        self.conditions_text = tk.Text(
            conditions_body, wrap=tk.WORD, state=tk.DISABLED,
            bg=C["surface"], fg=C["text_primary"],
            font=_MONO_FONT(9), padx=10, pady=6, width=34,
            relief="flat", highlightthickness=0,
        )
        self.conditions_text.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        conditions_scroll = ttk.Scrollbar(
            conditions_body, orient="vertical", command=self.conditions_text.yview)
        self.conditions_text.configure(yscrollcommand=conditions_scroll.set)
        conditions_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Middle: chart panel (canvas mounts here after a fetch)
        chart_panel, self.canvas_frame, self.chart_title = self._panel(
            self.results_frame, "Chart")
        chart_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas_widget = None
        self.current_fig = None

        # Export buttons live in the Output step frame (out_frame); the
        # results panels above are revealed after a successful fetch.

        # Build step content
        self._build_step_widgets()

        # Help registration must happen after every button callback target
        # exists, because `register_help` pokes the widget tree and the
        # export command objects are created in `_build_step_widgets`.
        # Defer the export callback references until after _build_step_widgets()
        # has created them, because register_help pokes the widget and that can
        # trigger command lookups before the lazy-defined methods exist.
        self._deferred_help = [(self.root, CTX["root"])]
        register_help(self.location_cb, CTX["location"])
        register_help(self.custom_city_entry, CTX["location"])
        register_help(self.period_cb, CTX["period"])
        register_help(self.depth_cb, CTX["depth"])
        register_help(self.units_cb, CTX["units"])
        register_help(self.monthly_chk, CTX["monthly"])
        register_help(self.unify_chk, CTX["unify"])
        register_help(self.precip_threshold_spin, CTX["precip_threshold"])
        register_help(self.insights_chk, CTX["insights"])
        register_help(self.yearly_chk, CTX["yearly"])
        register_help(self.fetch_btn, CTX["fetch"])
        register_help(self.save_btn, CTX["save"])
        self._deferred_help.append((self.export_csv_btn, CTX["export_csv"]))
        register_help(self.export_chart_btn, CTX["chart_export"])
        register_help(self.quickchart_btn, CTX["quickchart"])
        register_help(self.set_api_key_btn, CTX["chart_token"])
        register_help(self.conditions_text, CTX["results"])
        for w in getattr(self, "_custom_range_widgets", []):
            register_help(w, CTX["period"])
        for w in getattr(self, "_month_widgets", []):
            register_help(w, CTX["period"])
        register_help(self.tree, CTX["results"])
        register_help(self.canvas_frame, CTX["results"])
        register_help(self.conditions_frame, CTX["results"])
        register_help(self.conditions_text, CTX["results"])
        for w in getattr(self, "_custom_range_widgets", []):
            register_help(w, CTX["period"])
        for w in getattr(self, "_month_widgets", []):
            register_help(w, CTX["period"])
        # Register the late-bound export callback references once the step 4
        # buttons have been created in _build_step_widgets.
        self._deferred_help.extend([
            (self.location_cb, CTX["location"]),
            (self.custom_city_entry, CTX["location"]),
            (self.period_cb, CTX["period"]),
            (self.depth_cb, CTX["depth"]),
            (self.units_cb, CTX["units"]),
            (self.monthly_chk, CTX["monthly"]),
            (self.unify_chk, CTX["unify"]),
            (self.precip_threshold_spin, CTX["precip_threshold"]),
            (self.insights_chk, CTX["insights"]),
            (self.yearly_chk, CTX["yearly"]),
            (self.fetch_btn, CTX["fetch"]),
            (self.save_btn, CTX["save"]),
            (self.export_csv_btn, CTX["export_csv"]),
            (self.export_chart_btn, CTX["chart_export"]),
            (self.quickchart_btn, CTX["quickchart"]),
            (self.set_api_key_btn, CTX["chart_token"]),
            (self.tree, CTX["results"]),
            (self.canvas_frame, CTX["results"]),
            (self.conditions_frame, CTX["results"]),
            (self.conditions_text, CTX["results"]),
        ])
        for target, context_id in self._deferred_help:
            register_help(target, context_id)

        # Insights panel
        # Show first step
        self._show_step(0)

    def _build_step_widgets(self):
        """Create all widgets needed across steps (hidden by default)."""
        # ── Step 1: Location ─────────────────────────────────────────
        loc_frame = tk.Frame(self.step_frame, bg=C["bg_light"])
        loc_frame.pack(fill=tk.X, pady=8)

        tk.Label(loc_frame, text="Location:", bg=C["bg_light"], fg=C["text_primary"],
                 font=_UI_FONT(11, "bold")).pack(side=tk.LEFT, padx=(0, 8))

        self._location_presets = ["Cape Town", "Johannesburg", "Durban", "Custom..."]
        self.location_var = tk.StringVar(value="Cape Town")
        self.location_cb = ttk.Combobox(loc_frame, textvariable=self.location_var,
                                        values=self._location_presets,
                                        state="readonly", width=18)
        self.location_cb.pack(side=tk.LEFT, padx=(0, 12))
        self.location_cb.bind("<<ComboboxSelected>>", self._on_location_changed)
        Tooltip(self.location_cb, "Select a preset location or choose 'Custom...'.")

        self.custom_city_var = tk.StringVar()
        self.custom_city_entry = ttk.Entry(loc_frame, textvariable=self.custom_city_var, width=24)
        self.custom_city_entry.bind("<Escape>", self._on_custom_city_escape)
        Tooltip(self.custom_city_entry, "Enter any location name recognised by the weather API.")

        # Info text for step 1
        self.step1_info = tk.Label(loc_frame, text="",
                                    bg=C["bg_light"], fg=C["text_secondary"],
                                    font=_UI_FONT(9), justify=tk.LEFT)
        self.step1_info.pack(side=tk.LEFT, padx=(12, 0))

        # ── Step 2: Time Period ──────────────────────────────────────
        time_frame = tk.Frame(self.step_frame, bg=C["bg_light"])
        time_frame.pack(fill=tk.X, pady=8)

        # Main row with Period, Depth, Units in a horizontal layout
        main_row = tk.Frame(time_frame, bg=C["bg_light"])
        main_row.pack(side=tk.TOP, fill=tk.X)

        tk.Label(main_row, text="Period:", bg=C["bg_light"], fg=C["text_primary"],
                 font=_UI_FONT(11, "bold")).pack(side=tk.LEFT, padx=(0, 4))

        self.period_var = tk.StringVar(value="Summer")
        self.period_cb = ttk.Combobox(main_row, textvariable=self.period_var,
                                      values=["Summer", "Autumn", "Winter", "Spring",
                                              "Full Year", "Month", "Custom Range"],
                                      state="readonly", width=14)
        self.period_cb.pack(side=tk.LEFT, padx=(0, 16))
        self.period_cb.bind("<<ComboboxSelected>>", self._on_period_changed)
        Tooltip(self.period_cb, "Season, full year, month, or custom day-month range.")

        tk.Label(main_row, text="Depth:", bg=C["bg_light"], fg=C["text_primary"],
                 font=_UI_FONT(11, "bold")).pack(side=tk.LEFT, padx=(0, 4))
        self.depth_var = tk.IntVar(value=10)
        self.depth_cb = ttk.Combobox(main_row, textvariable=self.depth_var,
                                     values=["1", "3", "5", "7", "10", "15", "20"],
                                     state="readonly", width=5)
        self.depth_cb.pack(side=tk.LEFT, padx=(0, 16))
        Tooltip(self.depth_cb, "Years of history to average.")

        tk.Label(main_row, text="Units:", bg=C["bg_light"], fg=C["text_primary"],
                 font=_UI_FONT(11, "bold")).pack(side=tk.LEFT, padx=(0, 4))
        self.units_var = tk.StringVar(value="metric")
        self.units_cb = ttk.Combobox(main_row, textvariable=self.units_var,
                                     values=["metric", "imperial"],
                                     state="readonly", width=10)
        self.units_cb.pack(side=tk.LEFT, padx=(0, 12))
        Tooltip(self.units_cb, "Metric = °C / mm; Imperial = °F / inches.")

        # Conditional selectors frame (hidden by default, shown on same row when needed)
        self._conditional_frame = tk.Frame(time_frame, bg=C["bg_light"])
        
        self._cr_start_label = tk.Label(self._conditional_frame, text="From:", bg=C["bg_light"],
                                        fg=C["text_primary"], font=_UI_FONT(9))
        self._cr_start_day = tk.StringVar(value="1")
        self._cr_start_day_cb = ttk.Combobox(self._conditional_frame, textvariable=self._cr_start_day,
                                              values=[str(d) for d in range(1, 32)],
                                              state="readonly", width=3)
        self._cr_start_month = tk.StringVar(value="Jan")
        self._cr_start_month_cb = ttk.Combobox(self._conditional_frame, textvariable=self._cr_start_month,
                                                values=["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                                        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
                                                state="readonly", width=4)

        self._cr_end_label = tk.Label(self._conditional_frame, text="To:", bg=C["bg_light"],
                                      fg=C["text_primary"], font=_UI_FONT(9))
        self._cr_end_day = tk.StringVar(value="31")
        self._cr_end_day_cb = ttk.Combobox(self._conditional_frame, textvariable=self._cr_end_day,
                                            values=[str(d) for d in range(1, 32)],
                                            state="readonly", width=3)
        self._cr_end_month = tk.StringVar(value="Mar")
        self._cr_end_month_cb = ttk.Combobox(self._conditional_frame, textvariable=self._cr_end_month,
                                              values=["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                                      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
                                              state="readonly", width=4)

        self._custom_range_widgets = [
            self._cr_start_label, self._cr_start_day_cb, self._cr_start_month_cb,
            self._cr_end_label, self._cr_end_day_cb, self._cr_end_month_cb,
        ]
        for w in self._custom_range_widgets:
            w.pack(side=tk.LEFT, padx=(0, 2))

        self._month_label = tk.Label(self._conditional_frame, text="Month:", bg=C["bg_light"],
                                     fg=C["text_primary"], font=_UI_FONT(9))
        self._month_select_var = tk.StringVar(value="Jan")
        self._month_select_cb = ttk.Combobox(self._conditional_frame, textvariable=self._month_select_var,
                                              values=["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                                      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
                                              state="readonly", width=4)
        self._month_widgets = [self._month_label, self._month_select_cb]
        for w in self._month_widgets:
            w.pack(side=tk.LEFT, padx=(0, 2))

        # Info text for step 2
        self.step2_info = tk.Label(time_frame, text="",
                                    bg=C["bg_light"], fg=C["text_secondary"],
                                    font=_UI_FONT(9), justify=tk.LEFT)
        self.step2_info.pack(side=tk.BOTTOM, fill=tk.X, pady=(4, 0))

        # ── Step 3: Weather Options ──────────────────────────────────
        opt_frame = tk.Frame(self.step_frame, bg=C["bg_light"])
        opt_frame.pack(fill=tk.X, pady=8)

        # Graph options — bordered option cards (design '.checkbox-group')
        graph_opts = tk.Frame(opt_frame, bg=C["bg_light"])
        graph_opts.pack(side=tk.TOP, fill=tk.X, pady=(0, 8))

        self.monthly_var = tk.BooleanVar(value=True)
        self.monthly_chk = self._option_card(graph_opts, "Monthly Average",
                                             self.monthly_var)
        Tooltip(self.monthly_chk, "Show averages per month; otherwise day-of-year.")

        self.unify_var = tk.BooleanVar(value=True)
        self.unify_chk = self._option_card(graph_opts, "Shared Y-Axis",
                                           self.unify_var)
        Tooltip(self.unify_chk, "Same Y-axis range for temperature and precipitation.")

        # Minimum precipitation threshold — an option card with an inline spinbox.
        self.precip_threshold_var = tk.DoubleVar(value=5.0)
        precip_card = self._option_card_frame(graph_opts)
        self.precip_threshold_spin = ttk.Spinbox(
            precip_card, from_=0, to=50, increment=0.5,
            textvariable=self.precip_threshold_var, width=6)
        self.precip_threshold_spin.pack(side=tk.RIGHT, padx=10, pady=6)
        tk.Label(precip_card, text="Minimum precipitation (mm):", bg=C["bg_light"],
                 fg=C["text_secondary"], font=_UI_FONT(9)).pack(side=tk.RIGHT,
                                                                padx=(0, 8))
        Tooltip(self.precip_threshold_spin,
                "Minimum precipitation on the chart: values below this mm are "
                "treated as zero (excludes dew/frost).")

        # Reporting options — bordered option cards.
        report_opts = tk.Frame(opt_frame, bg=C["bg_light"])
        report_opts.pack(side=tk.TOP, fill=tk.X)

        self.insights_var = tk.BooleanVar(value=True)
        self.insights_chk = self._option_card(report_opts, "Conditions & Extremes",
                                              self.insights_var)
        Tooltip(self.insights_chk, "Show most common conditions and ranges/extremes.")

        self.yearly_var = tk.BooleanVar(value=False)
        self.yearly_chk = self._option_card(report_opts, "Yearly Breakdown",
                                            self.yearly_var)
        Tooltip(self.yearly_chk, "Per-year averages/totals with trend-per-decade.")

        # Info text for step 3
        self.step3_info = tk.Label(opt_frame, text="",
                                    bg=C["bg_light"], fg=C["text_secondary"],
                                    font=_UI_FONT(9), justify=tk.LEFT)
        self.step3_info.pack(side=tk.TOP, fill=tk.X, pady=(8, 0))

        # ── Step 4: Output ───────────────────────────────────────────
        out_frame = tk.Frame(self.step_frame, bg=C["bg_light"])
        out_frame.pack(fill=tk.X, pady=8)

        # Export buttons (design '.output-buttons'); the results panels
        # below are revealed only after a successful fetch.
        self.save_btn = ttk.Button(out_frame, text="Save JPG", command=self.save_to_jpg,
                                   state="disabled")
        self.save_btn.pack(side=tk.LEFT, padx=(0, 8))
        Tooltip(self.save_btn, "Save the current chart as JPEG.")

        self.export_csv_btn = ttk.Button(out_frame, text="Export CSV", command=self.export_csv,
                                         state="disabled")
        self.export_csv_btn.pack(side=tk.LEFT, padx=(0, 8))
        Tooltip(self.export_csv_btn, "Export processed data as CSV.")

        self.export_chart_btn = ttk.Button(out_frame, text="Datawrapper", command=self.export_csv_and_chart,
                                           state="disabled")
        self.export_chart_btn.pack(side=tk.LEFT, padx=(0, 8))
        Tooltip(self.export_chart_btn, "Publish an interactive chart via Datawrapper.")

        self.quickchart_btn = ttk.Button(out_frame, text="QuickChart PNG",
                                         command=self.export_quickchart_png, state="disabled")
        self.quickchart_btn.pack(side=tk.LEFT, padx=(0, 8))
        Tooltip(self.quickchart_btn, "Render PNG via QuickChart (no account needed).")

        self.set_api_key_btn = ttk.Button(out_frame, text="Datawrapper Token",
                                          command=self.set_datawrapper_token)
        self.set_api_key_btn.pack(side=tk.LEFT, padx=(0, 8))
        Tooltip(self.set_api_key_btn, "Set / verify your Datawrapper API token.")

        # Summary info for step 4
        self.step4_info = tk.Label(out_frame, text="",
                                    bg=C["bg_light"], fg=C["text_secondary"],
                                    font=_UI_FONT(9), justify=tk.LEFT)
        self.step4_info.pack(side=tk.LEFT, padx=(24, 0), fill=tk.X, expand=True)

        # Store references to all step frames for showing/hiding
        self._step_widgets = {
            0: {"frame": loc_frame, "info": self.step1_info},
            1: {"frame": time_frame, "info": self.step2_info},
            2: {"frame": opt_frame, "info": self.step3_info},
            3: {"frame": out_frame, "info": self.step4_info},
        }

    def _show_step(self, step, animate=False):
        """Show the given step's widgets and update navigation.
        
        Args:
            step: The step index to show (0-3)
            animate: If True, apply fade/slide animation (disabled by default)
        """
        # Hide all step content immediately (animations disabled for reliability)
        for s, widgets in self._step_widgets.items():
            widgets["frame"].pack_forget()

        # Show current step
        current = self._step_widgets[step]
        current["frame"].pack(fill=tk.X, pady=8)

        # Design header: eyebrow (subtitle, uppercase) + title + blurb
        step_def = WIZARD_STEPS[step]
        self.eyebrow_label.config(text=step_def["subtitle"].upper())
        self.step_title_label.config(text=f"{step + 1}. {step_def['title']}")
        self.step_blurb_label.config(text=step_def["blurb"])

        # Sidebar highlight + progress strip
        self._paint_sidebar(step)
        completed = list(range(step))
        self.progress.set_step(step, completed)
        if step == self.current_step:
            self.progress.start_pulse()
        else:
            self.progress.stop_pulse()
            self.progress.start_pulse()

        # Output step extras: results panels appear once data has been fetched
        has_results = getattr(self, "_last_df", None) is not None
        if step == len(WIZARD_STEPS) - 1 and has_results:
            self.results_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(12, 0))
        else:
            self.results_frame.pack_forget()

        # Update navigation buttons
        self.back_btn.config(state="normal" if step > 0 else "disabled")
        if step == len(WIZARD_STEPS) - 1:
            self.next_btn.config(state="disabled")
            self.fetch_btn.config(state="normal")
            self.next_btn.pack_forget()
            self.fetch_btn.pack(side=tk.LEFT, padx=(0, 8))
        else:
            self.next_btn.config(state="normal")
            self.fetch_btn.pack_forget()
            self.next_btn.pack(side=tk.LEFT, padx=(0, 8))

        # Update info text for each step
        self._update_step_info(step)

        self.current_step = step

    def _fade_out_step(self, callback=None):
        """Fade out the current step frame with a slide-up effect.
        
        Since Tkinter doesn't support true opacity, we simulate the effect
        by hiding child widgets sequentially and applying a visual transition.
        """
        if not hasattr(self, '_current_step_frame'):
            if callback:
                callback()
            return
        
        frame = self._current_step_frame
        if not hasattr(frame, '_slide_after_id'):
            frame._slide_after_id = None
        
        # Store initial position
        if not hasattr(frame, '_slide_pos'):
            frame._slide_pos = 0
        
        # Get the number of child widgets to animate
        children = list(frame.winfo_children())
        total_children = len(children)
        
        def slide_up_and_fade(step=0):
            if step < total_children:
                # Hide one widget at a time for sequential effect
                if step < total_children:
                    child = children[step]
                    child.pack_forget()
                frame._slide_after_id = frame.after(40, lambda: slide_up_and_fade(step + 1))
            else:
                # All children hidden, now hide the frame itself
                frame.pack_forget()
                self._current_step_frame = None
                if hasattr(frame, '_slide_after_id'):
                    frame.after_cancel(frame._slide_after_id)
                    frame._slide_after_id = None
                if callback:
                    callback()
        
        if frame._slide_after_id:
            frame.after_cancel(frame._slide_after_id)
        slide_up_and_fade()

    def _fade_in_step(self, frame, callback=None):
        """Fade in a step frame with a slide-up entrance effect.
        
        Shows widgets sequentially with a slight delay for a cascading effect.
        """
        if not hasattr(frame, '_slide_after_id'):
            frame._slide_after_id = None
        
        # Pack the frame first
        frame.pack(fill=tk.X, pady=8)
        
        # Get child widgets and show them in sequence
        children = list(frame.winfo_children())
        
        def cascade_show(step=0):
            if step < len(children):
                child = children[step]
                child.pack_configure()  # Make visible
                child.update_idletasks()
                frame._slide_after_id = frame.after(30, lambda: cascade_show(step + 1))
            else:
                if hasattr(frame, '_slide_after_id'):
                    frame.after_cancel(frame._slide_after_id)
                    frame._slide_after_id = None
                if callback:
                    callback()
        
        # Start with frame visible but children hidden, then cascade in
        for child in children:
            child.pack_forget()
        
        frame._slide_after_id = frame.after(50, lambda: cascade_show(0))

    def _validate_current_step(self):
        """Validate required fields on the current step.
        
        Returns True if valid, False if there's an error.
        Shows an error message if validation fails.
        """
        step = self.current_step
        
        if step == 0:
            # Step 1: Location - validate custom city if selected
            if self.location_var.get() == "Custom...":
                city = self.custom_city_var.get().strip()
                if not city:
                    messagebox.showwarning(
                        "Location Required",
                        "Please enter a city name for your custom location.",
                        parent=self.root
                    )
                    self.custom_city_entry.focus_set()
                    return False
        
        elif step == 1:
            # Step 2: Time Period - validate custom range if selected
            if self.period_var.get() == "Custom Range":
                # Basic validation - the date pickers have defaults so this
                # is more about ensuring the user has noticed them
                pass
        
        # Steps 2 and 3 have no required fields (all optional toggles)
        
        return True

    def _update_step_info(self, step):
        """Update the info text for the current step."""
        if step == 0:
            city = self._get_city()
            if city:
                self.step1_info.config(text=f"Analysing: {city}")
            else:
                self.step1_info.config(text="Select a location to begin")
        elif step == 1:
            period = self.period_var.get()
            depth = self.depth_var.get()
            units = self.units_var.get()
            unit_label = "°C / mm" if units == "metric" else "°F / inches"
            self.step2_info.config(text=f"Period: {period} | Depth: {depth} years | Units: {unit_label}")
        elif step == 2:
            options = []
            if self.monthly_var.get():
                options.append("Monthly")
            if self.unify_var.get():
                options.append("Shared Y-Axis")
            if self.insights_var.get():
                options.append("Conditions")
            if self.yearly_var.get():
                options.append("Yearly")
            precip = self.precip_threshold_var.get()
            opt_text = ", ".join(options) if options else "None"
            self.step3_info.config(text=f"Options: {opt_text} | Min Precip: {precip} mm")
        elif step == 3:
            if hasattr(self, '_last_city') and hasattr(self, '_last_period'):
                self.step4_info.config(text=f"Last analysis: {self._last_city} — {self._last_period}")
            else:
                self.step4_info.config(text="Fetch data to see results and export options")

    # ── Event handlers ────────────────────────────────────────────────
    def _go_next(self):
        """Advance to next step, with validation for required fields."""
        # Validate current step before advancing
        if not self._validate_current_step():
            return
        
        if self.current_step < len(WIZARD_STEPS) - 1:
            self._show_step(self.current_step + 1)

    def _go_back(self):
        """Go back to previous step (no validation needed)."""
        if self.current_step > 0:
            self._show_step(self.current_step - 1)

    def _show_location_widget(self, widget):
        """Pack the location combobox or custom entry in its slot."""
        widget.pack_forget()
        widget.pack(side=tk.LEFT, padx=(0, 12))

    def _on_location_changed(self, event=None):
        if self.location_var.get() == "Custom...":
            self._show_location_widget(self.custom_city_entry)
            self.location_cb.pack_forget()
            self.custom_city_entry.focus_set()
        else:
            self._show_location_widget(self.location_cb)
            self.custom_city_entry.pack_forget()
        self._update_step_info(self.current_step)

    def _on_custom_city_escape(self, event=None):
        self.custom_city_entry.pack_forget()
        self.location_var.set(self._location_presets[0])
        self._show_location_widget(self.location_cb)
        self._update_step_info(self.current_step)

    def _on_period_changed(self, event=None):
        period = self.period_var.get()

        # Reset both selector groups, then show whichever applies.
        for w in self._custom_range_widgets:
            w.pack_forget()
        for w in self._month_widgets:
            w.pack_forget()
        self._conditional_frame.pack_forget()

        if period == "Custom Range":
            for w in self._custom_range_widgets:
                w.pack(side=tk.LEFT, padx=(0, 2))
            self._conditional_frame.pack(side=tk.TOP, fill=tk.X, pady=(4, 0))
            self.monthly_chk.config(state="disabled")
        elif period == "Month":
            for w in self._month_widgets:
                w.pack(side=tk.LEFT, padx=(0, 2))
            self._conditional_frame.pack(side=tk.TOP, fill=tk.X, pady=(4, 0))
            self.monthly_chk.config(state="disabled")
        else:
            self.monthly_chk.config(state="normal")

        self._update_step_info(self.current_step)

    def _get_city(self):
        if self.location_var.get() == "Custom...":
            return self.custom_city_var.get().strip()
        return self.location_var.get()

    def fetch_data_thread(self):
        city = self._get_city()
        if not city:
            logger.warning("Fetch attempted with empty city name")
            messagebox.showerror("Error", "Please enter a city or location name.",
                                 parent=self.root)
            return

        self.fetch_btn.config(state="disabled")
        self.save_btn.config(state="disabled")
        self.export_csv_btn.config(state="disabled")
        self.export_chart_btn.config(state="disabled")
        self.quickchart_btn.config(state="disabled")
        self.status_var.set("Fetching coordinates…")
        self.status_label.config(fg=C["temp_warm"])
        self.tree.delete(*self.tree.get_children())
        if self.canvas_widget:
            self.canvas_widget.get_tk_widget().destroy()
            self.canvas_widget = None
        self.current_fig = None
        # Clear the analysis summary margin too
        if hasattr(self, "conditions_text"):
            self.conditions_text.config(state=tk.NORMAL)
            self.conditions_text.delete("1.0", tk.END)
            self.conditions_text.config(state=tk.DISABLED)

        # Show the temperature range bar while fetching
        self.timeline.pack_forget()
        self.timeline.pack(side=tk.TOP, fill=tk.X, before=self.step_frame,
                           pady=(6, 0))
        self.timeline.start()

        params = {
            "city": city,
            "period": self.period_var.get(),
            "depth": self.depth_var.get(),
            "units": self.units_var.get(),
            "monthly": self.monthly_var.get(),
            "unify_scales": self.unify_var.get(),
            "precip_threshold": self.precip_threshold_var.get(),
            "insights": self.insights_var.get(),
            "yearly": self.yearly_var.get(),
        }
        if params["period"] == "Custom Range":
            params["start_month"] = self._month_to_num[self._cr_start_month.get()]
            params["start_day"] = int(self._cr_start_day.get())
            params["end_month"] = self._month_to_num[self._cr_end_month.get()]
            params["end_day"] = int(self._cr_end_day.get())
        elif params["period"] == "Month":
            params["selected_month"] = self._month_to_num[self._month_select_var.get()]

        logger.info("Fetch started: %s", params)
        threading.Thread(target=self.process_data, args=(params,), daemon=True).start()

    def process_data(self, params):
        city = params["city"]
        period = params["period"]
        depth = params["depth"]
        units = params["units"]
        monthly = params["monthly"]
        unify_scales = params["unify_scales"]
        precip_threshold = params["precip_threshold"]

        try:
            lat, lon = get_coordinates(city)
            self.root.after(0, lambda: self.status_var.set(
                f"Fetching historical data for {city}…"))

            current_year = datetime.now().year
            end_year = current_year - 1
            start_year = end_year - depth + 1
            is_custom = period == "Custom Range"
            is_month = period == "Month"

            if is_custom:
                sm = params["start_month"]
                sday = params["start_day"]
                em = params["end_month"]
                eday = params["end_day"]
            elif is_month:
                m = params["selected_month"]
                sm, sday, em, eday = m, 1, m, self._last_days[m]
            else:
                sm, sday, em, eday = None, None, None, None

            # Cross-year windows need one extra leading year
            if is_custom or is_month:
                extra_year = sm > em
            else:
                wsm, wem = get_season_months(period)
                extra_year = wsm > wem
            start_date = f"{start_year - 1 if extra_year else start_year}-01-01"
            end_date = f"{end_year}-12-31"

            if is_custom:
                num_to_month = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
                                7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}
                display_period = f"Custom: {sday} {num_to_month[sm]} – {eday} {num_to_month[em]}"
            elif is_month:
                display_period = datetime(2000, m, 1).strftime("%B")
            else:
                display_period = period

            custom_start = (sm, sday) if is_custom or is_month else None
            custom_end = (em, eday) if is_custom or is_month else None

            raw_data = fetch_historical_weather(lat, lon, start_date, end_date)
            self.root.after(0, lambda: self.status_var.set("Processing and generating chart…"))
            processed_df = process_weather_data(
                raw_data, period, units, monthly,
                custom_start=custom_start, custom_end=custom_end,
                precip_threshold=precip_threshold)

            if processed_df.empty:
                raise ValueError("No data available for the given timeframe.")

            # Feed the analysed temperature range to the timeline
            temp_range_min = processed_df['temp_min'].min()
            temp_range_max = processed_df['temp_max'].max()
            if units == "imperial":
                temp_range_min = (temp_range_min - 32.0) * 5.0 / 9.0
                temp_range_max = (temp_range_max - 32.0) * 5.0 / 9.0
            self.timeline.set_temperature_range(temp_range_min, temp_range_max)

            if is_custom:
                monthly = custom_range_days(sm, sday, em, eday) > 31

            insights_text = ""
            if params.get("insights") or params.get("yearly"):
                insights_text = build_insights_text(
                    raw_data, period, custom_start, custom_end, units,
                    show_insights=params.get("insights", False),
                    show_yearly=params.get("yearly", False),
                    precip_threshold=precip_threshold, max_years=depth)

            fig = create_visualization_figure(processed_df, city, display_period,
                                              units, monthly, unify_scales)

            self._last_city = city
            self._last_period = display_period
            self._last_depth = depth
            self._last_units = units
            self.root.after(0, self.update_ui, processed_df, fig, units, insights_text)

        except Exception as e:
            logger.error("Error during data fetch/processing", exc_info=True)
            msg = str(e)
            if "Failed to get coordinates" in msg or "coordinates" in msg.lower():
                msg = f"Could not find coordinates for '{city}'. Check the spelling."
            elif "No data available" in msg:
                msg = f"No weather data found for '{city}' with the selected parameters."
            self.root.after(0, self.show_error, msg)

    def update_ui(self, df, fig, units, insights_text=""):
        self.current_fig = fig
        self._last_df = df

        # Stop timeline
        self.timeline.stop()
        self.timeline.pack_forget()

        temp_unit = "°F" if units == "imperial" else "°C"
        precip_unit = "inch" if units == "imperial" else "mm"

        for _, row in df.iterrows():
            self.tree.insert("", tk.END, values=(
                row['date_label'],
                f"{row['temp_max']:.1f} {temp_unit}",
                f"{row['temp_min']:.1f} {temp_unit}",
                f"{row['precip_sum']:.1f} {precip_unit}",
            ))

        self.chart_title.config(
            text=f"Chart — Historical Weather for {getattr(self, '_last_city', '—')} "
                 f"({getattr(self, '_last_period', '')})")
        self.canvas_widget = FigureCanvasTkAgg(self.current_fig, master=self.canvas_frame)
        self.canvas_widget.draw()
        self.canvas_widget.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Populate the analysis summary margin next to the chart (right-hand side)
        self._render_conditions_summary(df, units, insights_text)

        self.status_var.set("Ready.")
        self.status_label.config(fg=C["text_secondary"])
        self.fetch_btn.config(state="normal")
        self.save_btn.config(state="normal")
        self.export_csv_btn.config(state="normal")
        self.export_chart_btn.config(state="normal")
        self.quickchart_btn.config(state="normal")

        # Update step 4 info with results summary
        if hasattr(self, '_last_city'):
            self.step4_info.config(text=f"Results: {self._last_city} — {self._last_period} ({self._last_depth} years)")

        # Auto-switch to output step (results panels reveal with it)
        self._show_step(3)
        self.save_settings()

    def _render_conditions_summary(self, df, units, insights_text=""):
        """Populate the right-hand margin beside the chart.

        Shows a compact climate summary up top, then the full structured
        output (conditions, variability, year-over-year) below it.
        """
        if not hasattr(self, "conditions_text"):
            return
        text = self.conditions_text
        text.config(state=tk.NORMAL)
        text.delete("1.0", tk.END)
        precip_unit = "inch" if units == "imperial" else "mm"
        temp_unit = "°F" if units == "imperial" else "°C"
        hdr_kwargs = {"font": _UI_FONT(9, "bold"), "foreground": C["deep_ocean"],
                      "spacing1": 4, "spacing3": 2}

        def add(content, tag=None):
            text.insert(tk.END, content + "\n", tag)

        add("Climate Summary", "hdr")
        add(f"Location: {getattr(self, '_last_city', '—')}")
        if not df.empty:
            mean_max = df["temp_max"].mean()
            mean_min = df["temp_min"].mean()
            add(f"Mean temperature: {mean_min:.1f} … {mean_max:.1f} {temp_unit}")
            mean_precip = df["precip_sum"].mean()
            add(f"Mean precipitation: {mean_precip:.1f} {precip_unit}")
        else:
            add("Fetch data to see conditions.")
        add("")
        text.tag_configure("hdr", **hdr_kwargs)

        if insights_text:
            tag_i = 0
            for line in insights_text.splitlines():
                stripped = line.strip()
                if (stripped and not stripped.startswith(("-", " ", "+"))
                        and not stripped[0].isdigit()):
                    tag = f"hdr{tag_i}"
                    tag_i += 1
                    text.insert(tk.END, line + "\n", tag)
                    text.tag_configure(tag, **hdr_kwargs)
                else:
                    text.insert(tk.END, line + "\n")
        else:
            add("Enable 'Conditions & Extremes' or 'Yearly Breakdown' on the "
                "Weather Options step for the full analysis.", "muted")
            text.tag_configure("muted", foreground=C["text_muted"])
        text.config(state=tk.DISABLED)

    # ── Datawrapper ───────────────────────────────────────────────────
    def set_datawrapper_token(self):
        """Set / replace the stored Datawrapper API token (persisted per machine)."""
        stored = getattr(self, "_datawrapper_token", "") or _read_api_token()
        if stored:
            self._datawrapper_token = stored
        else:
            answer = messagebox.askyesno(
                "API Token Required",
                "No Datawrapper API token is stored yet.\n\n"
                "The token is saved in the Windows registry (macOS: Keychain) so you "
                "won't be asked again.\n\nOpen the Datawrapper token page now?",
                parent=self.root,
            )
            if answer:
                _open_api_key_site()
        token = self._prompt_for_token(
            initialvalue=getattr(self, "_datawrapper_token", ""))
        if not token:
            return
        _write_api_token(token)
        self.save_settings()
        self.status_var.set("Datawrapper token saved.")

    def _prompt_for_token(self, initialvalue="", title="Datawrapper API Token"):
        """Ask the user for a Datawrapper API token and keep it on self.

        Returns the trimmed token, or an empty string if cancelled/invalid.
        """
        token = simpledialog.askstring(
            title,
            "Enter your Datawrapper API token\n"
            "(app.datawrapper.de → Settings & Account → API tokens):",
            initialvalue=initialvalue, show="*", parent=self.root)
        if token is None:
            return ""
        token = token.strip()
        if not token:
            messagebox.showwarning("Datawrapper Token", "Token cannot be empty.",
                                   parent=self.root)
            return ""
        self._datawrapper_token = token
        return token

    def _verify_datawrapper_token(self, token):
        from datawrapper_client import check_credentials
        problem = check_credentials(token)

        def report():
            self.status_var.set("Ready.")
            if problem is None:
                messagebox.showinfo("Datawrapper Token Saved",
                                    "Token verified against the Datawrapper API.",
                                    parent=self.root)
            else:
                messagebox.showwarning("Datawrapper Token",
                                       f"Token saved, but the API check failed:\n\n{problem}",
                                       parent=self.root)
        self.root.after(0, report)

    def _require_last_data(self):
        if not hasattr(self, '_last_city') or not hasattr(self, '_last_period'):
            messagebox.showwarning("Warning", "No data — fetch data first.",
                                   parent=self.root)
            return None
        if not hasattr(self, '_last_df'):
            messagebox.showwarning("Warning", "No processed data — fetch again.",
                                   parent=self.root)
            return None
        return self._last_df, self._last_city, self._last_period

    def _export_csv_step(self, df, city, period):
        try:
            export_to_csv(df, city, period)
            logger.info("CSV exported")
            return True
        except Exception as e:
            logger.error("CSV export failed", exc_info=True)
            messagebox.showerror("Error", f"CSV export failed:\n{e}", parent=self.root)
            return False

    def export_csv(self):
        if not hasattr(self, '_last_city') or not hasattr(self, '_last_period'):
            messagebox.showwarning("Warning", "No data available — fetch data first.",
                                   parent=self.root)
            return
        try:
            if not hasattr(self, '_last_df'):
                messagebox.showwarning("Warning", "No processed data stored — fetch again.",
                                       parent=self.root)
                return
            filename = export_to_csv(self._last_df, self._last_city, self._last_period)
            messagebox.showinfo("Success", f"Data exported to {filename}", parent=self.root)
        except Exception as e:
            logger.error("Failed to export CSV", exc_info=True)
            messagebox.showerror("Error", f"Failed to export CSV:\n{e}", parent=self.root)

    def export_csv_and_chart(self):
        data = self._require_last_data()
        if data is None:
            return
        df, city, period = data

        token = self._ensure_api_token()
        if not token:
            return

        if not self._export_csv_step(df, city, period):
            return

        self.export_chart_btn.config(state="disabled")
        self.status_var.set("Publishing Datawrapper chart…")
        threading.Thread(target=self._datawrapper_worker,
                         args=(df, city, period, getattr(self, '_last_units', 'metric'), token),
                         daemon=True).start()

    def _datawrapper_worker(self, df, city, period, units, token):
        from datawrapper_client import DatawrapperError, create_chart

        def report_success(result):
            self.status_var.set("Ready.")
            self.export_chart_btn.config(state="normal")
            if messagebox.askyesno("Datawrapper Success",
                                   f"Chart published!\n\n{result['url']}\n\nOpen in browser?",
                                   parent=self.root):
                webbrowser.open(result["url"])

        def report_failure(message):
            self.status_var.set("Datawrapper export failed.")
            self.export_chart_btn.config(state="normal")
            messagebox.showerror("Datawrapper Error", message, parent=self.root)

        try:
            result = create_chart(df, city, period, units, token)
        except DatawrapperError as e:
            logger.error("Datawrapper API error: %s", e)
            self.root.after(0, report_failure, str(e))
        except Exception as e:
            logger.error("Unexpected Datawrapper failure", exc_info=True)
            self.root.after(0, report_failure,
                            f"Unexpected problem:\n{e.__class__.__name__}: {e}")
        else:
            self.root.after(0, report_success, result)

    # ── QuickChart PNG ────────────────────────────────────────────────
    def export_quickchart_png(self):
        data = self._require_last_data()
        if data is None:
            return
        df, city, period = data

        # Show save dialog first
        from tkinter import filedialog
        filepath = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG files", "*.png"), ("JPEG files", "*.jpg"), ("All files", "*.*")],
            title="Save QuickChart PNG",
            initialfile=self._generate_filename().replace('.jpg', '.png'))
        
        if not filepath:
            self.quickchart_btn.config(state="normal")
            return

        self.quickchart_btn.config(state="disabled")
        self.status_var.set("Rendering via QuickChart…")
        threading.Thread(target=self._quickchart_worker,
                         args=(df, city, period, getattr(self, '_last_units', 'metric'), filepath),
                         daemon=True).start()

    def _quickchart_worker(self, df, city, period, units, filepath):
        from quickchart_client import QuickChartError, export_chart_png

        def report_success(saved_path):
            self.status_var.set("Ready.")
            self.quickchart_btn.config(state="normal")
            if messagebox.askyesno("QuickChart Success",
                                   f"Chart saved:\n\n{saved_path}\n\nOpen now?",
                                   parent=self.root):
                # Open in default image viewer instead of browser
                os.startfile(saved_path)

        def report_failure(message):
            self.status_var.set("QuickChart export failed.")
            self.quickchart_btn.config(state="normal")
            messagebox.showerror("QuickChart Error", message, parent=self.root)

        try:
            filepath = export_chart_png(df, city, period, units)
        except QuickChartError as e:
            logger.error("QuickChart error: %s", e)
            self.root.after(0, report_failure, str(e))
        except Exception as e:
            logger.error("Unexpected QuickChart failure", exc_info=True)
            self.root.after(0, report_failure,
                            f"Unexpected problem:\n{e.__class__.__name__}: {e}")
        else:
            self.root.after(0, report_success, filepath)

    # ── Save JPG ──────────────────────────────────────────────────────
    def _generate_filename(self):
        city = getattr(self, '_last_city', 'weather')
        period = getattr(self, '_last_period', '')
        depth = getattr(self, '_last_depth', '')
        safe_city = re.sub(r'[^\w\-]', '_', city)
        safe_period = re.sub(r'[^\w\-]', '_', period)
        if depth:
            return f"{depth}yr_{safe_period}_{safe_city}.jpg"
        return f"{safe_period}_{safe_city}.jpg"

    def save_to_jpg(self):
        if self.current_fig:
            from tkinter import filedialog
            filepath = filedialog.asksaveasfilename(
                defaultextension=".jpg",
                filetypes=[("JPEG files", "*.jpg"), ("PNG files", "*.png"),
                           ("All files", "*.*")],
                title="Save Chart as JPG",
                initialfile=self._generate_filename())
            if filepath:
                try:
                    fmt = "png" if filepath.lower().endswith(".png") else "jpg"
                    self.current_fig.savefig(filepath, format=fmt, dpi=300)
                    logger.info("Chart saved to %s", filepath)
                    messagebox.showinfo("Success", f"Chart saved to:\n{filepath}",
                                        parent=self.root)
                except Exception as e:
                    logger.error("Failed to save chart", exc_info=True)
                    messagebox.showerror("Error", f"Failed to save image:\n{e}",
                                         parent=self.root)

    def show_error(self, message):
        messagebox.showerror("Error", message, parent=self.root)
        self.status_var.set("Error.")
        self.status_label.config(fg=C["danger"])
        self.fetch_btn.config(state="normal")
        self.save_btn.config(state="disabled")
        self.export_csv_btn.config(state="disabled")
        self.export_chart_btn.config(state="disabled")
        self.quickchart_btn.config(state="disabled")
        self.timeline.stop()
        self.timeline.pack_forget()
        if hasattr(self, "conditions_text"):
            self.conditions_text.config(state=tk.NORMAL)
            self.conditions_text.delete("1.0", tk.END)
            self.conditions_text.insert(
                tk.END,
                "An error occurred while fetching data.\n"
                "Review the message above and try again.\n",
            )
            self.conditions_text.config(state=tk.DISABLED)

    # ── Settings ──────────────────────────────────────────────────────
    def load_settings(self):
        if os.path.isfile(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    self._settings = json.load(f)
                logger.info("Loaded settings from %s", SETTINGS_FILE)
            except Exception as e:
                logger.warning("Could not load settings: %s", e)
                self._settings = {}
        else:
            self._settings = {}

    def apply_settings(self):
        s = self._settings
        if not s:
            return
        city = s.get("city")
        if city in self._location_presets:
            self.location_var.set(city)
            self._on_location_changed()
            if city == "Custom...":
                self.custom_city_var.set(s.get("custom_city", ""))
        else:
            self.location_var.set(self._location_presets[0])
            self._on_location_changed()

        period = s.get("period")
        if period in ["Summer", "Autumn", "Winter", "Spring", "Full Year", "Month", "Custom Range"]:
            self.period_var.set(period)
            self._on_period_changed()

        depth = s.get("depth")
        if depth in [1, 3, 5, 7, 10, 15, 20]:
            self.depth_var.set(depth)

        units = s.get("units")
        if units in ["metric", "imperial"]:
            self.units_var.set(units)

        if isinstance(s.get("monthly"), bool):
            self.monthly_var.set(s["monthly"])
        if isinstance(s.get("unify_scales"), bool):
            self.unify_var.set(s["unify_scales"])
        if isinstance(s.get("precip_threshold"), (int, float)):
            self.precip_threshold_var.set(float(s["precip_threshold"]))
        if isinstance(s.get("insights"), bool):
            self.insights_var.set(s["insights"])
        if isinstance(s.get("yearly"), bool):
            self.yearly_var.set(s["yearly"])

        if s.get("start_month") is not None:
            self._cr_start_month.set(list(self._month_to_num.keys())[s["start_month"] - 1])
        if s.get("start_day") is not None:
            self._cr_start_day.set(str(s["start_day"]))
        if s.get("end_month") is not None:
            self._cr_end_month.set(list(self._month_to_num.keys())[s["end_month"] - 1])
        if s.get("end_day") is not None:
            self._cr_end_day.set(str(s["end_day"]))
        if s.get("selected_month") is not None:
            self._month_select_var.set(list(self._month_to_num.keys())[s["selected_month"] - 1])

        token = s.get("datawrapper_token") or ""
        stored = _read_api_token() or ""
        if token and not stored:
            # One-time migration of a legacy token that used to live in the
            # settings file — move it into the OS store, then stop persisting
            # it in plaintext settings from now on.
            self._datawrapper_token = token
            _write_api_token(token)
            logger.info("Migrated Datawrapper token from settings file to OS store")
        else:
            self._datawrapper_token = stored
            if stored:
                logger.info("Loaded Datawrapper token from persistent store")

        # Update UI to reflect loaded settings
        self._update_step_info(0)

    def save_settings(self):
        s = {}
        if self.location_var.get() == "Custom...":
            s["city"] = "Custom..."
            s["custom_city"] = self.custom_city_var.get().strip()
        else:
            s["city"] = self.location_var.get()
        s["period"] = self.period_var.get()
        s["depth"] = self.depth_var.get()
        s["units"] = self.units_var.get()
        s["monthly"] = self.monthly_var.get()
        s["unify_scales"] = self.unify_var.get()
        s["precip_threshold"] = self.precip_threshold_var.get()
        s["insights"] = self.insights_var.get()
        s["yearly"] = self.yearly_var.get()
        s["start_month"] = self._month_to_num.get(self._cr_start_month.get())
        s["start_day"] = int(self._cr_start_day.get()) if self._cr_start_day.get() else None
        s["end_month"] = self._month_to_num.get(self._cr_end_month.get())
        s["end_day"] = int(self._cr_end_day.get()) if self._cr_end_day.get() else None
        s["selected_month"] = self._month_to_num.get(self._month_select_var.get())
        try:
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(s, f, indent=2)
            logger.info("Saved settings to %s", SETTINGS_FILE)
        except Exception as e:
            logger.error("Failed to save settings: %s", e)

    def _ensure_api_token(self):
        """Return a stored Datawrapper token, prompting when one is missing.

        Used on first publish: offers to open the token page before asking the
        user to paste a token, then persists it so they are never asked again.
        """
        stored = getattr(self, "_datawrapper_token", "") or _read_api_token()
        if stored:
            self._datawrapper_token = stored
            return stored
        answer = messagebox.askyesno(
            "API Token Required",
            "You asked to publish a Datawrapper chart, but no API token is stored yet.\n\n"
            "The token is saved in the Windows registry (macOS: Keychain) so you won't "
            "be asked again.\n\nOpen the Datawrapper token page now?",
            parent=self.root,
        )
        if answer:
            _open_api_key_site()
        token = self._prompt_for_token()
        if not token:
            return ""
        _write_api_token(token)
        self.save_settings()
        return token

    def on_closing(self):
        self.save_settings()
        close_all()
        self.root.destroy()


if __name__ == "__main__":
    setup_logging()
    logger.info("WeatherSnake UI starting")
    root = tk.Tk()
    app = WeatherJuiceApp(root)
    root.mainloop()
