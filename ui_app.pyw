"""WeatherSnake GUI — weather-appropriate visual theme.

Visual identity:
  Palette: deep ocean ink (#1A2332), warm/cool temperature tones (#E67E22 / #3B82F6),
  precipitation blue (#60A5FA), near-white workspace (#F8FAFC).
  Typography: Inter → Segoe UI → Helvetica (first family present on the system);
  JetBrains Mono → Consolas for tabular numbers. All lookups happen at startup.
  Signature: a temperature range bar that maps the analysed min/max onto a
  fixed -15 °C … +40 °C blue→orange gradient while data loads.

Layout: one controls panel on top (header row, conditional selectors row,
status row) and a data-table + chart + insights area below. All functionality
from earlier versions is preserved: F1 help, Ctrl+R/S/E shortcuts, settings
persistence, Datawrapper/QuickChart export, insights panel.
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

    # LabelFrame - weather data sections
    style.configure("TLabelFrame", background=C["bg_light"], foreground=C["deep_ocean"],
                    font=(_UI_FONT_NAME, 10, "bold"), relief="flat", borderwidth=1)
    style.map("TLabelFrame",
              background=[("active", "#FFFFFF")],
              foreground=[("active", C["temp_warm"])])

    # Buttons - weather action controls
    style.configure("TButton", padding=(14, 8), font=(_UI_FONT_NAME, 9, "bold"),
                    background=C["surface"], foreground=C["text_primary"],
                    borderwidth=1, relief="solid")
    style.map("TButton",
              background=[("active", C["temp_cool"])],
              foreground=[("active", "#FFFFFF"),
                          ("!disabled", C["text_primary"])])

    # Accent button variant - primary weather actions
    style.configure("Accent.TButton", background=C["temp_warm"], foreground="#FFFFFF",
                    relief="flat", padding=(16, 10))
    style.map("Accent.TButton",
              background=[("active", "#D35400")],
              foreground=[("active", "#FFFFFF")])

    # Checkbuttons - weather options
    style.configure("TCheckbutton", background=C["bg_light"], foreground=C["text_primary"],
                    font=(_UI_FONT_NAME, 9))

    # Combobox - data selection
    style.configure("TCombobox", fieldbackground=C["input_bg"],
                    arrowcolor=C["deep_ocean"], relief="flat")
    style.map("TCombobox", fieldbackground=[("readonly", C["input_bg"])])

    # Entry / Spinbox - numeric inputs
    style.configure("TSpinbox", fieldbackground=C["input_bg"], relief="flat")

    # Treeview - weather data table
    style.configure("Treeview", background=C["surface"], foreground=C["text_primary"],
                    fieldbackground=C["surface"], font=(_MONO_FONT_NAME, 9),
                    rowheight=28, borderwidth=0)
    style.configure("Treeview.Heading", font=(_UI_FONT_NAME, 9, "bold"),
                    background=C["deep_ocean"], foreground="#FFFFFF")
    style.map("Treeview",
              background=[("selected", C["precipitation"])],
              foreground=[("selected", "#FFFFFF")])


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
#  Main application
# ══════════════════════════════════════════════════════════════════════════
class WeatherJuiceApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} v{VERSION}")
        self.root.geometry("1180x680")
        self.root.minsize(980, 600)
        self.root.configure(bg=C["bg_light"])
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        setup_styles(self.root)
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

    # ── Widgets ───────────────────────────────────────────────────────
    def create_widgets(self):
        # ── Top: controls ────────────────────────────────────────────
        ctrl = ttk.LabelFrame(self.root, text="  Weather Controls  ", padding="12 10")
        ctrl.pack(side=tk.TOP, fill=tk.X, padx=12, pady=(10, 4))

        # Signature element sits above the controls, inside the same panel.
        self.timeline = TemperatureTimeline(ctrl)

        # Row 0 — main row (kept on self so the timeline can pack before it)
        row0 = tk.Frame(ctrl, bg=C["bg_light"])
        row0.pack(fill=tk.X)
        self._controls_row0 = row0

        # Location
        tk.Label(row0, text="Location:", bg=C["bg_light"], fg=C["text_primary"],
                 font=_UI_FONT(9, "bold")).pack(in_=row0, side=tk.LEFT, padx=(0, 4))
        self._location_presets = ["Cape Town", "Johannesburg", "Durban", "Custom..."]
        self.location_var = tk.StringVar(value="Cape Town")
        self.location_cb = ttk.Combobox(row0, textvariable=self.location_var,
                                        values=self._location_presets,
                                        state="readonly", width=16)
        self.location_cb.pack(in_=row0, side=tk.LEFT, padx=(0, 8))
        self.location_cb.bind("<<ComboboxSelected>>", self._on_location_changed)
        Tooltip(self.location_cb, "Select a preset location or choose 'Custom...'.")

        self.custom_city_var = tk.StringVar()
        self.custom_city_entry = ttk.Entry(row0, textvariable=self.custom_city_var, width=20)
        self.custom_city_entry.bind("<Escape>", self._on_custom_city_escape)
        self.custom_city_entry.pack_forget()
        Tooltip(self.custom_city_entry, "Enter any location name recognised by the weather API.")

        self._show_location_widget(self.location_cb)

        # Period
        tk.Label(row0, text="Period:", bg=C["bg_light"], fg=C["text_primary"],
                 font=_UI_FONT(9, "bold")).pack(in_=row0, side=tk.LEFT, padx=(12, 4))
        self.period_var = tk.StringVar(value="Summer")
        self.period_cb = ttk.Combobox(row0, textvariable=self.period_var,
                                      values=["Summer", "Autumn", "Winter", "Spring",
                                              "Full Year", "Month", "Custom Range"],
                                      state="readonly", width=12)
        self.period_cb.pack(in_=row0, side=tk.LEFT, padx=(0, 8))
        self.period_cb.bind("<<ComboboxSelected>>", self._on_period_changed)
        Tooltip(self.period_cb, "Season, full year, month, or custom day-month range.")

        # Depth
        tk.Label(row0, text="Depth:", bg=C["bg_light"], fg=C["text_primary"],
                 font=_UI_FONT(9, "bold")).pack(in_=row0, side=tk.LEFT, padx=(12, 4))
        self.depth_var = tk.IntVar(value=10)
        self.depth_cb = ttk.Combobox(row0, textvariable=self.depth_var,
                                     values=["1", "3", "5", "7", "10", "15", "20"],
                                     state="readonly", width=5)
        self.depth_cb.pack(in_=row0, side=tk.LEFT, padx=(0, 8))
        Tooltip(self.depth_cb, "Years of history to average.")

        # Units
        tk.Label(row0, text="Units:", bg=C["bg_light"], fg=C["text_primary"],
                 font=_UI_FONT(9, "bold")).pack(in_=row0, side=tk.LEFT, padx=(12, 4))
        self.units_var = tk.StringVar(value="metric")
        self.units_cb = ttk.Combobox(row0, textvariable=self.units_var,
                                     values=["metric", "imperial"],
                                     state="readonly", width=9)
        self.units_cb.pack(in_=row0, side=tk.LEFT, padx=(0, 8))
        Tooltip(self.units_cb, "Metric = °C / mm; Imperial = °F / inches.")

        # ── Action buttons ──────────────────────────────────────────
        btn_row = tk.Frame(ctrl, bg=C["bg_light"])
        btn_row.pack(fill=tk.X, pady=(8, 0))

        self.fetch_btn = ttk.Button(btn_row, text="Fetch Data", command=self.fetch_data_thread,
                                    style="Accent.TButton")
        self.fetch_btn.pack(side=tk.LEFT, padx=(0, 6))
        Tooltip(self.fetch_btn, "Retrieve weather data and regenerate the chart.")

        self.save_btn = ttk.Button(btn_row, text="Save JPG", command=self.save_to_jpg,
                                   state="disabled")
        self.save_btn.pack(side=tk.LEFT, padx=(0, 6))
        Tooltip(self.save_btn, "Save the current chart as JPEG.")

        self.export_csv_btn = ttk.Button(btn_row, text="Export CSV", command=self.export_csv,
                                         state="disabled")
        self.export_csv_btn.pack(side=tk.LEFT, padx=(0, 6))
        Tooltip(self.export_csv_btn, "Export processed data as CSV.")

        self.export_chart_btn = ttk.Button(btn_row, text="Datawrapper", command=self.export_csv_and_chart,
                                           state="disabled")
        self.export_chart_btn.pack(side=tk.LEFT, padx=(0, 6))
        Tooltip(self.export_chart_btn, "Publish an interactive chart via Datawrapper.")

        self.quickchart_btn = ttk.Button(btn_row, text="QuickChart PNG",
                                         command=self.export_quickchart_png, state="disabled")
        self.quickchart_btn.pack(side=tk.LEFT, padx=(0, 6))
        Tooltip(self.quickchart_btn, "Render PNG via QuickChart (no account needed).")

        self.set_api_key_btn = ttk.Button(btn_row, text="Datawrapper Token",
                                          command=self.set_datawrapper_token)
        self.set_api_key_btn.pack(side=tk.LEFT, padx=(0, 6))
        Tooltip(self.set_api_key_btn, "Set / verify your Datawrapper API token.")

        # ── Options row ─────────────────────────────────────────────
        opt_row = tk.Frame(ctrl, bg=C["bg_light"])
        opt_row.pack(fill=tk.X, pady=(6, 0))

        self.monthly_var = tk.BooleanVar(value=True)
        self.monthly_chk = ttk.Checkbutton(opt_row, text="Monthly Average",
                                           variable=self.monthly_var)
        self.monthly_chk.pack(side=tk.LEFT, padx=(0, 10))
        Tooltip(self.monthly_chk, "Show averages per month; otherwise day-of-year.")

        self.unify_var = tk.BooleanVar(value=True)
        self.unify_chk = ttk.Checkbutton(opt_row, text="Shared Y-Axis",
                                         variable=self.unify_var)
        self.unify_chk.pack(side=tk.LEFT, padx=(0, 10))
        Tooltip(self.unify_chk, "Same Y-axis range for temperature and precipitation.")

        self.insights_var = tk.BooleanVar(value=True)
        self.insights_chk = ttk.Checkbutton(opt_row, text="Conditions & Extremes",
                                            variable=self.insights_var)
        self.insights_chk.pack(side=tk.LEFT, padx=(0, 10))
        Tooltip(self.insights_chk, "Show most common conditions and ranges/extremes.")

        self.yearly_var = tk.BooleanVar(value=False)
        self.yearly_chk = ttk.Checkbutton(opt_row, text="Yearly Breakdown",
                                          variable=self.yearly_var)
        self.yearly_chk.pack(side=tk.LEFT, padx=(0, 10))
        Tooltip(self.yearly_chk, "Per-year averages/totals with trend-per-decade.")

        tk.Label(opt_row, text="Min Precip (mm):", bg=C["bg_light"], fg=C["text_secondary"],
                 font=_UI_FONT(9)).pack(side=tk.LEFT, padx=(12, 2))
        self.precip_threshold_var = tk.DoubleVar(value=5.0)
        self.precip_threshold_spin = ttk.Spinbox(opt_row, from_=0, to=50, increment=0.5,
                                                 textvariable=self.precip_threshold_var, width=6)
        self.precip_threshold_spin.pack(side=tk.LEFT, padx=(0, 8))
        Tooltip(self.precip_threshold_spin,
                "Values below this mm are treated as zero (excludes dew/frost).")

        # ── Row 1: conditional selectors (custom range / month) ─────
        row1 = tk.Frame(ctrl, bg=C["bg_light"])
        row1.pack(fill=tk.X, pady=(6, 0))

        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        day_values = [str(d) for d in range(1, 32)]

        self._cr_start_label = tk.Label(row1, text="From:", bg=C["bg_light"],
                                        fg=C["text_primary"], font=_UI_FONT(9))
        self._cr_start_day = tk.StringVar(value="1")
        self._cr_start_day_cb = ttk.Combobox(row1, textvariable=self._cr_start_day,
                                              values=day_values, state="readonly", width=3)
        self._cr_start_month = tk.StringVar(value="Jan")
        self._cr_start_month_cb = ttk.Combobox(row1, textvariable=self._cr_start_month,
                                                values=month_names, state="readonly", width=4)

        self._cr_end_label = tk.Label(row1, text="To:", bg=C["bg_light"],
                                      fg=C["text_primary"], font=_UI_FONT(9))
        self._cr_end_day = tk.StringVar(value="31")
        self._cr_end_day_cb = ttk.Combobox(row1, textvariable=self._cr_end_day,
                                            values=day_values, state="readonly", width=3)
        self._cr_end_month = tk.StringVar(value="Mar")
        self._cr_end_month_cb = ttk.Combobox(row1, textvariable=self._cr_end_month,
                                              values=month_names, state="readonly", width=4)

        self._custom_range_widgets = [
            self._cr_start_label, self._cr_start_day_cb, self._cr_start_month_cb,
            self._cr_end_label, self._cr_end_day_cb, self._cr_end_month_cb,
        ]
        for w in self._custom_range_widgets:
            w.pack_forget()

        self._month_to_num = {name: i + 1 for i, name in enumerate(month_names)}
        self._last_days = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
                           7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}

        # Month period selector (same row, hidden initially)
        self._month_label = tk.Label(row1, text="Month:", bg=C["bg_light"],
                                     fg=C["text_primary"], font=_UI_FONT(9))
        self._month_select_var = tk.StringVar(value="Jan")
        self._month_select_cb = ttk.Combobox(row1, textvariable=self._month_select_var,
                                              values=month_names, state="readonly", width=4)
        self._month_widgets = [self._month_label, self._month_select_cb]
        for w in self._month_widgets:
            w.pack_forget()

        # Status line on its own row so it never overlaps the selectors.
        status_row = tk.Frame(ctrl, bg=C["bg_light"])
        status_row.pack(fill=tk.X, pady=(6, 0))
        self.status_var = tk.StringVar(value="Ready.")
        self.status_label = tk.Label(status_row, textvariable=self.status_var,
                                     fg=C["text_secondary"], bg=C["bg_light"],
                                     font=_UI_FONT(9), anchor="w")
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # ── Bottom: data + chart ─────────────────────────────────────
        content = tk.Frame(self.root, bg=C["bg_light"])
        content.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=12, pady=(4, 10))

        # Left: data table
        self.tree_frame = ttk.Frame(content, width=320)
        self.tree_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))

        columns = ("Date", "Max Temp", "Min Temp", "Precip")
        self.tree = ttk.Treeview(self.tree_frame, columns=columns, show="headings", height=16)
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=76, anchor=tk.CENTER)

        tree_scroll = ttk.Scrollbar(self.tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.Y, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Right: chart canvas
        self.canvas_frame = ttk.Frame(content)
        self.canvas_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas_widget = None
        self.current_fig = None

        # ── Context-sensitive help registration ──────────────────────
        register_help(self.root, CTX["root"])
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
        register_help(self.export_csv_btn, CTX["export_csv"])
        register_help(self.export_chart_btn, CTX["chart_export"])
        register_help(self.quickchart_btn, CTX["quickchart"])
        register_help(self.set_api_key_btn, CTX["chart_token"])
        for w in self._custom_range_widgets:
            register_help(w, CTX["period"])
        for w in self._month_widgets:
            register_help(w, CTX["period"])
        register_help(self.tree, CTX["results"])
        register_help(self.canvas_frame, CTX["results"])

        # Insights panel
        self.insights_text = None
        self._insights_scroll = None

    # ── Event handlers ────────────────────────────────────────────────
    def _show_location_widget(self, widget):
        """Pack the location combobox or custom entry in its slot (same geometry
        options every time, so the widget never gets reparented out of row0)."""
        widget.pack_forget()
        widget.pack(in_=widget.master, side=tk.LEFT, padx=(0, 8))

    def _on_location_changed(self, event=None):
        if self.location_var.get() == "Custom...":
            self._show_location_widget(self.custom_city_entry)
            self.location_cb.pack_forget()
            self.custom_city_entry.focus_set()
        else:
            self._show_location_widget(self.location_cb)
            self.custom_city_entry.pack_forget()

    def _on_custom_city_escape(self, event=None):
        self.custom_city_entry.pack_forget()
        self.location_var.set(self._location_presets[0])
        self._show_location_widget(self.location_cb)

    def _on_period_changed(self, event=None):
        period = self.period_var.get()
        for w in self._custom_range_widgets:
            w.pack_forget()
        for w in self._month_widgets:
            w.pack_forget()

        if period == "Custom Range":
            # pack in a sub-frame-like row using pack(side=LEFT)
            for w in self._custom_range_widgets:
                w.pack(side=tk.LEFT, padx=2)
            self.monthly_chk.config(state="disabled")
        elif period == "Month":
            for w in self._month_widgets:
                w.pack(side=tk.LEFT, padx=2)
            self.monthly_chk.config(state="disabled")
        else:
            self.monthly_chk.config(state="normal")

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
        if self.insights_text is not None:
            self.insights_text.destroy()
            self.insights_text = None
        if getattr(self, "_insights_scroll", None) is not None:
            self._insights_scroll.destroy()
            self._insights_scroll = None
        self.current_fig = None

        # Show the temperature range bar while fetching (inside the controls
        # panel, directly under the header — never reparented).
        self.timeline.pack_forget()
        self.timeline.pack(side=tk.TOP, fill=tk.X, before=self._controls_row0,
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

            # Cross-year windows (e.g. Dec–Feb summer, custom 15 Nov – 28 Feb)
            # need one extra leading year so the earliest occurrence includes
            # its head month.
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

            # Feed the analysed temperature range to the timeline. The engine
            # returns converted values for imperial; convert back to °C so the
            # bar's fixed °C scale stays honest in both unit modes.
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

        self.canvas_widget = FigureCanvasTkAgg(self.current_fig, master=self.canvas_frame)
        self.canvas_widget.draw()
        self.canvas_widget.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Insights panel
        if self.insights_text is not None:
            self.insights_text.destroy()
            self.insights_text = None
        if getattr(self, "_insights_scroll", None) is not None:
            self._insights_scroll.destroy()
            self._insights_scroll = None

        if insights_text:
            self.insights_text = tk.Text(self.canvas_frame, height=9, wrap=tk.WORD,
                                         state=tk.NORMAL, relief=tk.FLAT,
                                         bg="#FFFFFF", fg=C["text_primary"],
                                         font=_UI_FONT(9), padx=8, pady=6)
            # Section headers ("Weather Conditions (historical)", "Variability
            # & Extremes", "Year-over-Year", …) get accent colour + weight.
            tag_i = 0
            for line in insights_text.splitlines():
                stripped = line.strip()
                if (stripped and not stripped.startswith(("-", " ", "+"))
                        and not stripped[0].isdigit()):
                    tag = f"hdr{tag_i}"
                    tag_i += 1
                    self.insights_text.insert(tk.END, line + "\n", tag)
                    self.insights_text.tag_configure(
                        tag, font=_UI_FONT(9, "bold"),
                        foreground=C["deep_ocean"],
                        spacing1=6, spacing3=2)
                else:
                    self.insights_text.insert(tk.END, line + "\n")
            self.insights_text.config(state=tk.DISABLED)
            scroll = ttk.Scrollbar(self.canvas_frame, orient="vertical",
                                   command=self.insights_text.yview)
            self.insights_text.configure(yscrollcommand=scroll.set)
            self.insights_text.pack(side=tk.TOP, fill=tk.X, padx=4, pady=(4, 0))
            scroll.pack(side=tk.RIGHT, fill=tk.Y)
            self._insights_scroll = scroll

        self.status_var.set("Ready.")
        self.status_label.config(fg=C["text_secondary"])
        self.fetch_btn.config(state="normal")
        self.save_btn.config(state="normal")
        self.export_csv_btn.config(state="normal")
        self.export_chart_btn.config(state="normal")
        self.quickchart_btn.config(state="normal")
        self.save_settings()

    # ── CSV export ────────────────────────────────────────────────────
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

    # ── Datawrapper ───────────────────────────────────────────────────
    def set_datawrapper_token(self):
        token = simpledialog.askstring(
            "Datawrapper API Token",
            "Enter your Datawrapper API token\n(app.datawrapper.de → Settings & Account → API tokens):",
            initialvalue=getattr(self, "_datawrapper_token", ""), show="*", parent=self.root)
        if token is None:
            return
        token = token.strip()
        if not token:
            messagebox.showwarning("Datawrapper Token", "Token cannot be empty.",
                                   parent=self.root)
            return
        self._datawrapper_token = token
        self.save_settings()
        self.status_var.set("Verifying token…")
        threading.Thread(target=self._verify_datawrapper_token, args=(token,), daemon=True).start()

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

    def export_csv_and_chart(self):
        data = self._require_last_data()
        if data is None:
            return
        df, city, period = data

        token = getattr(self, "_datawrapper_token", "") or os.getenv("DATAWRAPPER_ACCESS_TOKEN", "")
        if not token:
            messagebox.showwarning(
                "API Token Missing",
                "Datawrapper needs a free API token.\n\n"
                "Click 'Datawrapper Token' to enter it, or set DATAWRAPPER_ACCESS_TOKEN.",
                parent=self.root)
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

        self.quickchart_btn.config(state="disabled")
        self.status_var.set("Rendering via QuickChart…")
        threading.Thread(target=self._quickchart_worker,
                         args=(df, city, period, getattr(self, '_last_units', 'metric')),
                         daemon=True).start()

    def _quickchart_worker(self, df, city, period, units):
        from quickchart_client import QuickChartError, export_chart_png

        def report_success(filepath):
            self.status_var.set("Ready.")
            self.quickchart_btn.config(state="normal")
            if messagebox.askyesno("QuickChart Success",
                                   f"Chart saved:\n\n{filepath}\n\nOpen now?",
                                   parent=self.root):
                webbrowser.open(f"file:///{filepath.replace(os.sep, '/')}")

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

        self._datawrapper_token = s.get("datawrapper_token", "")

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
        s["datawrapper_token"] = getattr(self, "_datawrapper_token", "")
        try:
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(s, f, indent=2)
            logger.info("Saved settings to %s", SETTINGS_FILE)
        except Exception as e:
            logger.error("Failed to save settings: %s", e)

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