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

logger = logging.getLogger(__name__)

# Help context ids (values from help_launcher.TOPIC_IDS) for widgets.
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
    "infographic": TOPIC_IDS["exports"],
    "infogram_key": TOPIC_IDS["exports"],
    "results": TOPIC_IDS["interface"],
}

def _settings_path() -> str:
	"""Settings file location.

	Frozen (PyInstaller) builds write to the user's application-data directory
	so settings survive across runs and uninstalls cleanly; source runs keep
	the file next to the source for easy inspection.
	"""
	if getattr(sys, "frozen", False):
		base = os.environ.get("APPDATA") or os.path.expanduser("~")
		return os.path.join(base, "WeatherSnake", "ui_settings.json")
	return os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui_settings.json")


SETTINGS_FILE = _settings_path()


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
        x, y, _, cy = self.widget.bbox("insert")
        x = x + self.widget.winfo_rootx() + 25
        y = y + cy + self.widget.winfo_rooty() + 25
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)  # no decorations
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, justify=tk.LEFT,
                         background="#ffffe0", relief=tk.SOLID, borderwidth=1,
                         font=("tahoma", "8", "normal"))
        label.pack(ipadx=4, padx=4, pady=2)

    def hide_tip(self, event=None):
        tw = self.tipwindow
        self.tipwindow = None
        if tw:
            tw.destroy()


class TemplatePickerDialog:
    """Modal dialog listing the account's Infogram projects for template choice."""

    def __init__(self, parent, projects):
        self.result = None
        self.root = top = tk.Toplevel(parent)
        top.title("Choose Infogram Template")
        top.transient(parent)
        top.grab_set()
        top.resizable(True, True)

        ttk.Label(top, text=(
            "Pick the project WeatherSnake should use as its template.\n"
            "It needs a text block (title) and a table chart (data)."
        )).pack(anchor=tk.W, padx=12, pady=(12, 6))

        columns = ("title", "state", "modified")
        self.tree = ttk.Treeview(top, columns=columns, show="headings", height=12)
        self.tree.heading("title", text="Project")
        self.tree.heading("state", text="State")
        self.tree.heading("modified", text="Modified")
        self.tree.column("title", width=320)
        self.tree.column("state", width=90, anchor=tk.CENTER)
        self.tree.column("modified", width=160, anchor=tk.CENTER)
        for p in projects:
            self.tree.insert("", tk.END, iid=p["projectId"], values=(
                p["title"], p["state"], p["modifiedAt"]))
        self.tree.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)

        button_row = ttk.Frame(top)
        button_row.pack(fill=tk.X, padx=12, pady=(0, 12))
        select_btn = ttk.Button(button_row, text="Use Selected", command=self._use_selected)
        select_btn.pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(button_row, text="Cancel", command=top.destroy).pack(side=tk.RIGHT)
        ttk.Button(button_row, text="Enter ID manually…",
                   command=self._manual).pack(side=tk.LEFT)

        self.tree.bind("<Double-1>", lambda e: self._use_selected())
        self.tree.bind("<Return>", lambda e: self._use_selected())
        self.tree.focus_set()
        if self.tree.get_children():
            first = self.tree.get_children()[0]
            self.tree.selection_set(first)
            self.tree.focus(first)

        top.update_idletasks()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        top.wm_geometry(f"+{px + 60}+{py + 60}")
        top.protocol("WM_DELETE_WINDOW", top.destroy)
        top.wait_window()

    def _use_selected(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Choose Infogram Template",
                                   "Select a project first.", parent=self.root)
            return
        self.result = selection[0]
        self.root.destroy()

    def _manual(self):
        """Close the picker and fall through to manual ID entry."""
        self.manual_requested = True
        self.root.destroy()


class WeatherJuiceApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} v{VERSION}")
        self.root.geometry("1100x700")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

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

    # ----- Menu bar -----
    def create_menu(self):
        """Build the menu bar: File and Help."""
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
        """Show the About dialog."""
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

    # ----- F1 context-sensitive help -----
    def on_f1(self, event=None):
        """Open help for the focused widget (F1 anywhere in the app)."""
        widget = self.root.focus_get()
        if widget is None:
            widget = self.root
        return show_context_help(widget)

    def _help_event(self, event):
        """Tk <?> help-event handler; routes to the context help resolution."""
        self.on_f1(event)
        return "break"

    def create_widgets(self):
        # Top Frame for Inputs
        input_frame = ttk.LabelFrame(self.root, text="Settings", padding="10")
        input_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=10)

        # Location
        ttk.Label(input_frame, text="Location:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self._location_presets = ["Cape Town", "Johannesburg", "Durban", "Custom..."]
        self.location_var = tk.StringVar(value="Cape Town")
        self.location_cb = ttk.Combobox(input_frame, textvariable=self.location_var,
                                         values=self._location_presets, state="readonly", width=17)
        self.location_cb.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)
        self.location_cb.bind("<<ComboboxSelected>>", self._on_location_changed)
        self.create_tooltip(self.location_cb, "Select a preset location or choose 'Custom...' to enter your own.")

        # Custom location entry (initially hidden)
        self.custom_city_var = tk.StringVar()
        self.custom_city_entry = ttk.Entry(input_frame, textvariable=self.custom_city_var, width=20)
        self.custom_city_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)
        self.custom_city_entry.bind("<Escape>", self._on_custom_city_escape)
        self.custom_city_entry.grid_remove()
        self.create_tooltip(self.custom_city_entry, "Enter any location name recognized by the weather API.")

        # Period
        ttk.Label(input_frame, text="Period:").grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)
        self.period_var = tk.StringVar(value="Summer")
        self.period_cb = ttk.Combobox(input_frame, textvariable=self.period_var, values=["Summer", "Autumn", "Winter", "Spring", "Full Year", "Month", "Custom Range"], state="readonly", width=12)
        self.period_cb.grid(row=0, column=3, padx=5, pady=5, sticky=tk.W)
        self.period_cb.bind("<<ComboboxSelected>>", self._on_period_changed)
        self.create_tooltip(self.period_cb, "Select a season, full year, a specific month, or a custom day‑month range.")

        # Depth
        self.depth_label = ttk.Label(input_frame, text="Depth (Years):")
        self.depth_label.grid(row=0, column=4, padx=5, pady=5, sticky=tk.W)
        self.depth_var = tk.IntVar(value=10)
        self.depth_cb = ttk.Combobox(input_frame, textvariable=self.depth_var, values=["1", "3", "5", "7", "10", "15", "20"], state="readonly", width=5)
        self.depth_cb.grid(row=0, column=5, padx=5, pady=5, sticky=tk.W)
        self.create_tooltip(self.depth_cb, "Number of previous years to average (e.g., 10 = average of last 10 years).")

        # Units
        ttk.Label(input_frame, text="Units:").grid(row=0, column=6, padx=5, pady=5, sticky=tk.W)
        self.units_var = tk.StringVar(value="metric")
        self.units_cb = ttk.Combobox(input_frame, textvariable=self.units_var, values=["metric", "imperial"], state="readonly", width=10)
        self.units_cb.grid(row=0, column=7, padx=5, pady=5, sticky=tk.W)
        self.create_tooltip(self.units_cb, "Metric = °C and mm; Imperial = °F and inches.")

        # Monthly Checkbox
        self.monthly_var = tk.BooleanVar(value=True)
        self.monthly_chk = ttk.Checkbutton(input_frame, text="Monthly Average", variable=self.monthly_var)
        self.monthly_chk.grid(row=0, column=8, padx=10, pady=5, sticky=tk.W)
        self.create_tooltip(self.monthly_chk, "When checked, show averages per month; otherwise show day‑of‑year averages.")

        # Unify Scales Checkbox
        self.unify_var = tk.BooleanVar(value=True)
        self.unify_chk = ttk.Checkbutton(input_frame, text="Shared Y-Axis", variable=self.unify_var)
        self.unify_chk.grid(row=0, column=9, padx=10, pady=5, sticky=tk.W)
        self.create_tooltip(self.unify_chk, "Use the same Y‑axis range for temperature and precipitation bars.")

        # Precipitation Threshold
        ttk.Label(input_frame, text="Min Precip (mm):").grid(row=2, column=0, padx=5, pady=2, sticky=tk.W)
        self.precip_threshold_var = tk.DoubleVar(value=5.0)
        self.precip_threshold_spin = ttk.Spinbox(input_frame, from_=0, to=50, increment=0.5,
                                                  textvariable=self.precip_threshold_var, width=6)
        self.precip_threshold_spin.grid(row=2, column=1, padx=5, pady=2, sticky=tk.W)
        self.create_tooltip(self.precip_threshold_spin,
                            "Values below this threshold (mm) are treated as zero to exclude dew/frost.")

        # Insights Checkbox
        self.insights_var = tk.BooleanVar(value=True)
        self.insights_chk = ttk.Checkbutton(input_frame, text="Conditions & Extremes", variable=self.insights_var)
        self.insights_chk.grid(row=2, column=2, padx=10, pady=2, sticky=tk.W)
        self.create_tooltip(self.insights_chk,
                            "Show the most common weather conditions and typical ranges/extremes for the window.")

        # Yearly Breakdown Checkbox
        self.yearly_var = tk.BooleanVar(value=False)
        self.yearly_chk = ttk.Checkbutton(input_frame, text="Yearly Breakdown", variable=self.yearly_var)
        self.yearly_chk.grid(row=2, column=3, padx=10, pady=2, sticky=tk.W)
        self.create_tooltip(self.yearly_chk,
                            "Show per-year averages/totals and a trend-per-decade estimate.")

        # Fetch Button
        self.fetch_btn = ttk.Button(input_frame, text="Fetch Data", command=self.fetch_data_thread)
        self.fetch_btn.grid(row=0, column=10, padx=10, pady=5, sticky=tk.W)
        self.create_tooltip(self.fetch_btn, "Start the data retrieval and visualization process.")

        # Save Button
        self.save_btn = ttk.Button(input_frame, text="Save to JPG", command=self.save_to_jpg, state="disabled")
        self.save_btn.grid(row=0, column=11, padx=10, pady=5, sticky=tk.W)
        self.create_tooltip(self.save_btn, "Save the current chart as a JPEG image.")

        # Export CSV Button
        self.export_csv_btn = ttk.Button(input_frame, text="Export CSV", command=self.export_csv)
        self.export_csv_btn.grid(row=0, column=12, padx=10, pady=5, sticky=tk.W)
        self.create_tooltip(self.export_csv_btn, "Export the processed data to a CSV file.")

        # Export CSV & Infographic Button
        self.export_infographic_btn = ttk.Button(input_frame, text="CSV + Infographic", command=self.export_csv_and_infographic)
        self.export_infographic_btn.grid(row=0, column=13, padx=10, pady=5, sticky=tk.W)
        self.create_tooltip(self.export_infographic_btn,
                            "Export CSV and publish an Infogram infographic from a template (requires API token).")

        # Set Infogr.am API Key Button
        self.set_api_key_btn = ttk.Button(input_frame, text="Infogram Token", command=self.set_infogram_credentials)
        self.set_api_key_btn.grid(row=0, column=14, padx=10, pady=5, sticky=tk.W)
        self.create_tooltip(self.set_api_key_btn,
                            "Set your Infogram API token and template project ID (stored locally).")

        # Custom Range day/month selectors (row 1, initially hidden)
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        day_values = [str(d) for d in range(1, 32)]

        self._cr_start_label = ttk.Label(input_frame, text="From:")
        self._cr_start_day = tk.StringVar(value="1")
        self._cr_start_day_cb = ttk.Combobox(input_frame, textvariable=self._cr_start_day,
                                              values=day_values, state="readonly", width=3)
        self._cr_start_month = tk.StringVar(value="Jan")
        self._cr_start_month_cb = ttk.Combobox(input_frame, textvariable=self._cr_start_month,
                                                values=month_names, state="readonly", width=4)

        self._cr_end_label = ttk.Label(input_frame, text="To:")
        self._cr_end_day = tk.StringVar(value="31")
        self._cr_end_day_cb = ttk.Combobox(input_frame, textvariable=self._cr_end_day,
                                            values=day_values, state="readonly", width=3)
        self._cr_end_month = tk.StringVar(value="Mar")
        self._cr_end_month_cb = ttk.Combobox(input_frame, textvariable=self._cr_end_month,
                                              values=month_names, state="readonly", width=4)

        self._cr_start_label.grid(row=1, column=0, padx=5, pady=2, sticky=tk.W)
        self._cr_start_day_cb.grid(row=1, column=1, padx=(5, 0), pady=2, sticky=tk.W)
        self._cr_start_month_cb.grid(row=1, column=2, padx=(2, 5), pady=2, sticky=tk.W)
        self._cr_end_label.grid(row=1, column=3, padx=5, pady=2, sticky=tk.W)
        self._cr_end_day_cb.grid(row=1, column=4, padx=(5, 0), pady=2, sticky=tk.W)
        self._cr_end_month_cb.grid(row=1, column=5, padx=(2, 5), pady=2, sticky=tk.W)

        self._custom_range_widgets = [
            self._cr_start_label, self._cr_start_day_cb, self._cr_start_month_cb,
            self._cr_end_label, self._cr_end_day_cb, self._cr_end_month_cb,
        ]
        for w in self._custom_range_widgets:
            w.grid_remove()

        self._month_to_num = {name: i + 1 for i, name in enumerate(month_names)}
        self._last_days = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
                           7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}

        # Month period selector (row 1, initially hidden)
        self._month_label = ttk.Label(input_frame, text="Month:")
        self._month_select_var = tk.StringVar(value="Jan")
        self._month_select_cb = ttk.Combobox(input_frame, textvariable=self._month_select_var,
                                              values=month_names, state="readonly", width=4)
        self._month_label.grid(row=1, column=0, padx=5, pady=2, sticky=tk.W)
        self._month_select_cb.grid(row=1, column=1, padx=5, pady=2, sticky=tk.W)
        self._month_widgets = [self._month_label, self._month_select_cb]
        for w in self._month_widgets:
            w.grid_remove()

        # Loading Label
        self.status_var = tk.StringVar(value="Ready.")
        self.status_label = ttk.Label(input_frame, textvariable=self.status_var, foreground="gray")
        self.status_label.grid(row=3, column=0, columnspan=12, sticky=tk.W, padx=5, pady=2)

        # Bottom Frame for Content
        content_frame = ttk.Frame(self.root)
        content_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Left side: Treeview for data
        self.tree_frame = ttk.Frame(content_frame, width=300)
        self.tree_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        columns = ("Date", "Max Temp", "Min Temp", "Precip")
        self.tree = ttk.Treeview(self.tree_frame, columns=columns, show="headings", height=15)
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=80, anchor=tk.CENTER)

        tree_scroll = ttk.Scrollbar(self.tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)

        self.tree.pack(side=tk.LEFT, fill=tk.Y, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Right side: Canvas for Matplotlib
        self.canvas_frame = ttk.Frame(content_frame)
        self.canvas_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas_widget = None
        self.current_fig = None

        # ----- Context-sensitive help registration (F1) -----
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
        register_help(self.export_infographic_btn, CTX["infographic"])
        register_help(self.set_api_key_btn, CTX["infogram_key"])
        for w in self._custom_range_widgets:
            register_help(w, CTX["period"])
        for w in self._month_widgets:
            register_help(w, CTX["period"])
        register_help(self.tree, CTX["results"])
        register_help(self.canvas_frame, CTX["results"])

        # Insights panel (scrollable text under the chart)
        self.insights_text = None

    # ----- Tooltip helper -----
    def create_tooltip(self, widget, text):
        return Tooltip(widget, text)

    # ----- Settings persistence -----
    def load_settings(self):
        """Load UI settings from JSON file if present."""
        if os.path.isfile(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Store in a dict for later applying
                self._settings = data
                logger.info("Loaded UI settings from %s", SETTINGS_FILE)
            except Exception as e:
                logger.warning("Could not load settings file: %s", e)
                self._settings = {}
        else:
            self._settings = {}

    def apply_settings(self):
        """Apply loaded settings to widgets."""
        s = self._settings
        if not s:
            return
        # Location
        city = s.get("city")
        if city in self._location_presets:
            self.location_var.set(city)
            self._on_location_changed()  # show/hide custom entry
            if city == "Custom...":
                self.custom_city_var.set(s.get("custom_city", ""))
        else:
            # fallback to first preset
            self.location_var.set(self._location_presets[0])
            self._on_location_changed()
        # Period
        period = s.get("period")
        if period in ["Summer", "Autumn", "Winter", "Spring", "Full Year", "Month", "Custom Range"]:
            self.period_var.set(period)
            self._on_period_changed()
        # Depth
        depth = s.get("depth")
        if depth in [1, 3, 5, 7, 10, 15, 20]:
            self.depth_var.set(depth)
        # Units
        units = s.get("units")
        if units in ["metric", "imperial"]:
            self.units_var.set(units)
        # Monthly
        monthly = s.get("monthly")
        if isinstance(monthly, bool):
            self.monthly_var.set(monthly)
        # Unify scales
        unify = s.get("unify_scales")
        if isinstance(unify, bool):
            self.unify_var.set(unify)
        # Precip threshold
        precip = s.get("precip_threshold")
        if isinstance(precip, (int, float)):
            self.precip_threshold_var.set(float(precip))
        # Insights / yearly breakdown
        insights = s.get("insights")
        if isinstance(insights, bool):
            self.insights_var.set(insights)
        yearly = s.get("yearly")
        if isinstance(yearly, bool):
            self.yearly_var.set(yearly)
        # Custom range values
        if s.get("start_month") is not None:
            self._cr_start_month.set(list(self._month_to_num.keys())[s["start_month"]-1])
        if s.get("start_day") is not None:
            self._cr_start_day.set(str(s["start_day"]))
        if s.get("end_month") is not None:
            self._cr_end_month.set(list(self._month_to_num.keys())[s["end_month"]-1])
        if s.get("end_day") is not None:
            self._cr_end_day.set(str(s["end_day"]))
        # Month selector
        if s.get("selected_month") is not None:
            self._month_select_var.set(list(self._month_to_num.keys())[s["selected_month"]-1])
        # Infogram API credentials
        self._infograma_key = s.get("infograma_key", "")
        self._infograma_template = s.get("infograma_template", "")

    def save_settings(self):
        """Save current widget values to JSON file."""
        s = {}
        # Location
        if self.location_var.get() == "Custom...":
            s["city"] = "Custom..."
            s["custom_city"] = self.custom_city_var.get().strip()
        else:
            s["city"] = self.location_var.get()
        # Period
        s["period"] = self.period_var.get()
        # Depth
        s["depth"] = self.depth_var.get()
        # Units
        s["units"] = self.units_var.get()
        # Monthly
        s["monthly"] = self.monthly_var.get()
        # Unify scales
        s["unify_scales"] = self.unify_var.get()
        # Precip threshold
        s["precip_threshold"] = self.precip_threshold_var.get()
        # Insights / yearly breakdown
        s["insights"] = self.insights_var.get()
        s["yearly"] = self.yearly_var.get()
        # Custom range
        s["start_month"] = self._month_to_num.get(self._cr_start_month.get())
        s["start_day"] = int(self._cr_start_day.get()) if self._cr_start_day.get() else None
        s["end_month"] = self._month_to_num.get(self._cr_end_month.get())
        s["end_day"] = int(self._cr_end_day.get()) if self._cr_end_day.get() else None
        # Month selector
        s["selected_month"] = self._month_to_num.get(self._month_select_var.get())
        # Infogram API credentials
        s["infograma_key"] = getattr(self, "_infograma_key", "")
        s["infograma_template"] = getattr(self, "_infograma_template", "")
        try:
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(s, f, indent=2)
            logger.info("Saved UI settings to %s", SETTINGS_FILE)
        except Exception as e:
            logger.error("Failed to save settings: %s", e)

    def on_closing(self):
        """Handle window close event."""
        self.save_settings()
        close_all()
        self.root.destroy()

    # ----- Event handlers -----
    def _on_location_changed(self, event=None):
        if self.location_var.get() == "Custom...":
            self.location_cb.grid_remove()
            self.custom_city_entry.grid()
            self.custom_city_entry.focus_set()
        else:
            self.custom_city_entry.grid_remove()
            self.location_var.set(self.location_var.get())  # ensure consistent
            self.location_cb.grid()

    def _on_custom_city_escape(self, event=None):
        """Return to the preset combobox when Escape is pressed in the custom entry."""
        self.custom_city_entry.grid_remove()
        self.location_var.set(self._location_presets[0])
        self.location_cb.grid()

    def _on_period_changed(self, event=None):
        period = self.period_var.get()
        # Hide all optional rows first
        for w in self._custom_range_widgets:
            w.grid_remove()
        for w in self._month_widgets:
            w.grid_remove()

        if period == "Custom Range":
            for w in self._custom_range_widgets:
                w.grid()
            self.monthly_chk.config(state="disabled")
        elif period == "Month":
            for w in self._month_widgets:
                w.grid()
            self.monthly_chk.config(state="disabled")
        else:
            self.monthly_chk.config(state="normal")

    def _get_city(self):
        """Return the selected city name from either the preset or custom entry."""
        if self.location_var.get() == "Custom...":
            return self.custom_city_var.get().strip()
        return self.location_var.get()

    def fetch_data_thread(self):
        city = self._get_city()
        if not city:
            logger.warning("Fetch attempted with empty city name")
            messagebox.showerror("Error", "Please enter a city or location name.", parent=self.root)
            return

        self.fetch_btn.config(state="disabled")
        self.save_btn.config(state="disabled")
        self.export_csv_btn.config(state="disabled")
        self.export_infographic_btn.config(state="disabled")
        self.status_var.set("Fetching coordinates...")
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

        # Capture all widget values on the main thread for thread safety
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
        thread = threading.Thread(target=self.process_data, args=(params,))
        thread.daemon = True
        thread.start()

    def process_data(self, params):
        city = params["city"]
        period = params["period"]
        depth = params["depth"]
        units = params["units"]
        monthly = params["monthly"]
        unify_scales = params["unify_scales"]
        precip_threshold = params["precip_threshold"]
        is_custom = period in ("Custom Range", "Month")

        try:
            lat, lon = get_coordinates(city)

            self.root.after(0, lambda: self.status_var.set(f"Fetching historical data for {city}..."))

            current_year = datetime.now().year
            end_year = current_year - 1
            start_year = end_year - depth + 1
            # Cross-year windows (e.g. Dec-Feb summer) need one extra leading
            # year so the earliest occurrence includes its head month.
            if period == "Custom Range":
                extra_year = params["start_month"] > params["end_month"]
            elif period == "Month":
                extra_year = False
            else:
                wsm, wem = get_season_months(period)
                extra_year = wsm > wem
            start_date = f"{start_year - 1 if extra_year else start_year}-01-01"
            end_date = f"{end_year}-12-31"

            if period == "Custom Range":
                sm = params["start_month"]
                sday = params["start_day"]
                em = params["end_month"]
                eday = params["end_day"]
                custom_start = (sm, sday)
                custom_end = (em, eday)
                num_to_month = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
                                7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}
                display_period = f"Custom: {sday} {num_to_month[sm]} - {eday} {num_to_month[em]}"
            elif period == "Month":
                m = params["selected_month"]
                custom_start = (m, 1)
                custom_end = (m, self._last_days[m])
                import calendar
                display_period = calendar.month_name[m]
            else:
                custom_start = None
                custom_end = None
                display_period = period

            raw_data = fetch_historical_weather(lat, lon, start_date, end_date)

            self.root.after(0, lambda: self.status_var.set("Processing and generating chart..."))
            processed_df = process_weather_data(raw_data, period, units, monthly,
                                                custom_start=custom_start, custom_end=custom_end,
                                                precip_threshold=precip_threshold)

            if processed_df.empty:
                raise ValueError("No data available for the given timeframe.")

            # For custom/month periods, monthly flag is auto-determined by processing
            if is_custom:
                monthly = custom_range_days(custom_start[0], custom_start[1],
                                            custom_end[0], custom_end[1]) > 31

            insights_text = ""
            if params.get("insights") or params.get("yearly"):
                insights_text = build_insights_text(
                    raw_data, period, custom_start, custom_end, units,
                    show_insights=params.get("insights", False),
                    show_yearly=params.get("yearly", False),
                    precip_threshold=precip_threshold,
                    max_years=depth,
                )

            fig = create_visualization_figure(processed_df, city, display_period, units, monthly, unify_scales)

            self._last_city = city
            self._last_period = display_period
            self._last_depth = depth
            self._last_units = units

            self.root.after(0, self.update_ui, processed_df, fig, units, insights_text)

        except Exception as e:
            logger.error("Error during data fetch/processing", exc_info=True)
            # Provide more user-friendly message for common errors
            msg = str(e)
            if "Failed to get coordinates" in msg or "coordinates" in msg.lower():
                msg = f"Could not find coordinates for '{city}'. Please check the spelling or try a nearby major city."
            elif "No data available" in msg:
                msg = f"No weather data found for '{city}' with the selected parameters. Try a different period or depth."
            self.root.after(0, self.show_error, msg)

    def update_ui(self, df, fig, units, insights_text=""):
        self.current_fig = fig
        self._last_df = df
        # Update Treeview
        temp_unit = "°F" if units == "imperial" else "°C"
        precip_unit = "inch" if units == "imperial" else "mm"

        for _, row in df.iterrows():
            self.tree.insert("", tk.END, values=(
                row['date_label'],
                f"{row['temp_max']:.1f} {temp_unit}",
                f"{row['temp_min']:.1f} {temp_unit}",
                f"{row['precip_sum']:.1f} {precip_unit}"
            ))

        # Add Matplotlib Figure to Canvas
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
            self.insights_text = tk.Text(self.canvas_frame, height=12, wrap=tk.WORD,
                                         state=tk.NORMAL, relief=tk.FLAT,
                                         background="#f5f5f5")
            self.insights_text.insert("1.0", insights_text)
            self.insights_text.config(state=tk.DISABLED)
            scroll = ttk.Scrollbar(self.canvas_frame, orient="vertical",
                                   command=self.insights_text.yview)
            self.insights_text.configure(yscrollcommand=scroll.set)
            self.insights_text.pack(side=tk.TOP, fill=tk.BOTH, expand=False)
            scroll.pack(side=tk.RIGHT, fill=tk.Y)
            self._insights_scroll = scroll

        self.status_var.set("Ready.")
        self.fetch_btn.config(state="normal")
        self.save_btn.config(state="normal")
        self.export_csv_btn.config(state="normal")
        self.export_infographic_btn.config(state="normal")
        # Save settings after successful fetch
        self.save_settings()

    # ----- CSV Export -----
    def export_csv(self):
        """Export the current processed data to CSV using output.export_to_csv."""
        if not hasattr(self, '_last_city') or not hasattr(self, '_last_period'):
            messagebox.showwarning("Warning", "No data available to export. Please fetch data first.",
                                   parent=self.root)
            return
        try:
            # We need the processed DataFrame; we can regenerate or store it.
            # For simplicity, we'll call the processing again with last used params.
            # But we can store the last_df in update_ui.
            if not hasattr(self, '_last_df'):
                messagebox.showwarning("Warning", "No processed data stored. Please fetch data again.",
                                   parent=self.root)
                return
            df = self._last_df
            city = self._last_city
            period = self._last_period
            filename = export_to_csv(df, city, period)
            messagebox.showinfo("Success", f"Data exported to {filename}", parent=self.root)
        except Exception as e:
            logger.error("Failed to export CSV", exc_info=True)
            messagebox.showerror("Error", f"Failed to export CSV:\n{e}", parent=self.root)

    # ----- Infogram Integration -----
    def set_infogram_credentials(self):
        """Prompt for the Infogram API token, then pick the template project."""
        token = simpledialog.askstring(
            "Infogram API Token",
            "Enter your Infogram API token\n(infogram.com, account settings, API):",
            initialvalue=getattr(self, "_infograma_key", ""), show="*", parent=self.root)
        if token is None:
            return
        token = token.strip()
        if not token:
            messagebox.showwarning("Infogram Token", "The token cannot be empty.",
                                   parent=self.root)
            return
        # The project list comes from the network; fetch it off the UI thread.
        self.status_var.set("Fetching your Infogram projects...")
        threading.Thread(target=self._infogram_template_worker, args=(token,),
                         daemon=True).start()

    def _infogram_template_worker(self, token):
        """Background fetch of the project list for template selection."""
        from infogram_client import InfogramError, list_projects
        try:
            projects = list_projects(token)
        except InfogramError as e:
            logger.error("Infogram project list failed: %s", e)
            self.root.after(0, self._infogram_template_failed, token, str(e))
            return
        self.root.after(0, self._infogram_template_pick, token, projects)

    def _infogram_template_failed(self, token, message):
        """The list fetch failed (usually a bad token); offer manual entry."""
        self.status_var.set("Ready.")
        if not messagebox.askyesno(
                "Infogram Token",
                f"Could not fetch your Infogram projects:\n\n{message}\n\n"
                "Do you want to enter the template project ID manually instead?",
                parent=self.root):
            return
        self._ask_template_id(token)

    def _infogram_template_pick(self, token, projects):
        """Show the template picker, or explain when the account is empty."""
        self.status_var.set("Ready.")
        if not projects:
            messagebox.showinfo(
                "Infogram Token",
                "The token works, but this Infogram account has no projects yet.\n\n"
                "Create a template in Infogram first: a project containing a text "
                "block (for the title) and a table chart (for the data). Then press "
                "Infogram Token again to pick it.",
                parent=self.root)
            return
        dialog = TemplatePickerDialog(self.root, projects)
        chosen = dialog.result
        if chosen is None:
            if getattr(dialog, "manual_requested", False):
                self._ask_template_id(token)
            return
        self._save_infogram_credentials(token, chosen)

    def _ask_template_id(self, token):
        """Manual fallback: paste a template project ID directly."""
        template = simpledialog.askstring(
            "Infogram Template Project ID",
            "Enter the project ID of your Infogram template\n"
            "(the UUID from the project card's context menu, 'Copy project ID'):\n\n"
            "The template needs a text block and a table chart; WeatherSnake\n"
            "copies it and fills in your weather data.",
            initialvalue=getattr(self, "_infograma_template", ""), parent=self.root)
        if template is None or not template.strip():
            return
        self._save_infogram_credentials(token, template.strip())

    def _save_infogram_credentials(self, token, template):
        """Store the credentials and verify them against the API in the background."""
        self._infograma_key = token
        self._infograma_template = template
        self.save_settings()
        self.status_var.set("Verifying Infogram credentials...")
        threading.Thread(target=self._verify_infogram_credentials,
                         args=(self._infograma_key, self._infograma_template),
                         daemon=True).start()

    def _verify_infogram_credentials(self, token, template):
        """Background credential check; reports via parented dialog."""
        from infogram_client import check_credentials
        problem = check_credentials(token, template)
        def report():
            self.status_var.set("Ready.")
            if problem is None:
                messagebox.showinfo(
                    "Infogram Credentials Saved",
                    "Token and template verified against the Infogram API.",
                    parent=self.root)
            else:
                messagebox.showwarning(
                    "Infogram Credentials",
                    f"Credentials saved, but the API check failed:\n\n{problem}",
                    parent=self.root)
        self.root.after(0, report)

    def export_csv_and_infographic(self):
        """Export CSV, then create an Infogram infographic (runs in background)."""
        if not hasattr(self, '_last_city') or not hasattr(self, '_last_period'):
            messagebox.showwarning("Warning", "No data available to export. Please fetch data first.",
                                   parent=self.root)
            return
        if not hasattr(self, '_last_df'):
            messagebox.showwarning("Warning", "No processed data stored. Please fetch data again.",
                                   parent=self.root)
            return

        api_key = getattr(self, "_infograma_key", "") or os.getenv("INFOGRAM_API_TOKEN", "")
        template = getattr(self, "_infograma_template", "") or os.getenv("INFOGRAM_TEMPLATE_ID", "")
        if not api_key or not template:
            messagebox.showwarning(
                "API Credentials Missing",
                "Infogram needs an API token and a template project ID.\n\n"
                "Click 'Infogram Token' to enter both (token from Infogram "
                "account settings, API; template ID from the project card's "
                "context menu), or set INFOGRAM_API_TOKEN and "
                "INFOGRAM_TEMPLATE_ID environment variables.",
                parent=self.root)
            return

        df = self._last_df
        city = self._last_city
        period = self._last_period
        try:
            csv_filename = export_to_csv(df, city, period)
            logger.info("CSV exported to %s", csv_filename)
        except Exception as e:
            logger.error("Failed to export CSV", exc_info=True)
            messagebox.showerror("Error", f"Failed to export CSV:\n{e}", parent=self.root)
            return

        # The API call can take seconds; run it off the UI thread so the
        # window stays responsive, and report back via root.after.
        self.export_infographic_btn.config(state="disabled")
        self.status_var.set("Creating Infogram infographic...")
        threading.Thread(
            target=self._infogram_worker,
            args=(df, city, period, getattr(self, '_last_units', 'metric'), api_key, template),
            daemon=True).start()

    def _infogram_worker(self, df, city, period, units, api_key, template):
        """Background Infogram request; always reports the outcome to the UI."""
        from infogram_client import InfogramError, create_infographic

        def report_success(result):
            self.status_var.set("Ready.")
            self.export_infographic_btn.config(state="normal")
            if messagebox.askyesno(
                    "Infogram Success",
                    f"Infographic created successfully!\n\n{result['url']}\n\nOpen it in your browser now?",
                    parent=self.root):
                webbrowser.open(result["url"])

        def report_failure(message):
            self.status_var.set("Infogram export failed.")
            self.export_infographic_btn.config(state="normal")
            messagebox.showerror("Infogram Error", message, parent=self.root)

        try:
            result = create_infographic(df, city, period, units, api_key, template)
        except InfogramError as e:
            logger.error("Infogram API error: %s", e)
            self.root.after(0, report_failure, str(e))
        except Exception as e:
            logger.error("Unexpected Infogram failure", exc_info=True)
            self.root.after(0, report_failure,
                            f"Unexpected problem contacting Infogram:\n{e.__class__.__name__}: {e}")
        else:
            self.root.after(0, report_success, result)

    # ----- Existing methods -----
    def _generate_filename(self):
        """Generate a descriptive default filename from the last fetch parameters."""
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
                filetypes=[("JPEG files", "*.jpg"), ("All files", "*.*")],
                title="Save Chart as JPG",
                initialfile=self._generate_filename()
            )
            if filepath:
                try:
                    self.current_fig.savefig(filepath, format="jpg", dpi=300)
                    logger.info("Chart saved to %s", filepath)
                    messagebox.showinfo("Success", f"Chart saved successfully to:\n{filepath}", parent=self.root)
                except Exception as e:
                    logger.error("Failed to save chart to %s", filepath, exc_info=True)
                    messagebox.showerror("Error", f"Failed to save image:\n{e}", parent=self.root)

    def show_error(self, message):
        messagebox.showerror("Error", message, parent=self.root)
        self.status_var.set("Error occurred.")
        self.fetch_btn.config(state="normal")
        self.save_btn.config(state="disabled")
        self.export_csv_btn.config(state="disabled")
        self.export_infographic_btn.config(state="disabled")


if __name__ == "__main__":
    setup_logging()
    logger.info("Weather Juice UI starting")
    root = tk.Tk()
    app = WeatherJuiceApp(root)
    root.mainloop()