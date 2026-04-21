import logging
import re
import tkinter as tk
from tkinter import ttk, messagebox
import threading
from datetime import datetime

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from logger_setup import setup_logging
from api_client import get_coordinates, fetch_historical_weather
from processing import process_weather_data, custom_range_days
from output import create_visualization_figure

logger = logging.getLogger(__name__)

class WeatherJuiceApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Weather Juice v1.0")
        self.root.geometry("1100x700")
        
        self.create_widgets()

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

        # Custom location entry (initially hidden)
        self.custom_city_var = tk.StringVar()
        self.custom_city_entry = ttk.Entry(input_frame, textvariable=self.custom_city_var, width=20)
        self.custom_city_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)
        self.custom_city_entry.bind("<Escape>", self._on_custom_city_escape)
        self.custom_city_entry.grid_remove()

        # Period
        ttk.Label(input_frame, text="Period:").grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)
        self.period_var = tk.StringVar(value="Summer")
        self.period_cb = ttk.Combobox(input_frame, textvariable=self.period_var, values=["Summer", "Autumn", "Winter", "Spring", "Full Year", "Month", "Custom Range"], state="readonly", width=12)
        self.period_cb.grid(row=0, column=3, padx=5, pady=5, sticky=tk.W)
        self.period_cb.bind("<<ComboboxSelected>>", self._on_period_changed)

        # Depth
        self.depth_label = ttk.Label(input_frame, text="Depth (Years):")
        self.depth_label.grid(row=0, column=4, padx=5, pady=5, sticky=tk.W)
        self.depth_var = tk.IntVar(value=10)
        self.depth_cb = ttk.Combobox(input_frame, textvariable=self.depth_var, values=["1", "5", "10", "20"], state="readonly", width=5)
        self.depth_cb.grid(row=0, column=5, padx=5, pady=5, sticky=tk.W)

        # Units
        ttk.Label(input_frame, text="Units:").grid(row=0, column=6, padx=5, pady=5, sticky=tk.W)
        self.units_var = tk.StringVar(value="metric")
        self.units_cb = ttk.Combobox(input_frame, textvariable=self.units_var, values=["metric", "imperial"], state="readonly", width=10)
        self.units_cb.grid(row=0, column=7, padx=5, pady=5, sticky=tk.W)

        # Monthly Checkbox
        self.monthly_var = tk.BooleanVar(value=True)
        self.monthly_chk = ttk.Checkbutton(input_frame, text="Monthly Average", variable=self.monthly_var)
        self.monthly_chk.grid(row=0, column=8, padx=10, pady=5, sticky=tk.W)

        # Unify Scales Checkbox
        self.unify_var = tk.BooleanVar(value=True)
        self.unify_chk = ttk.Checkbutton(input_frame, text="Shared Y-Axis", variable=self.unify_var)
        self.unify_chk.grid(row=0, column=9, padx=10, pady=5, sticky=tk.W)

        # Fetch Button
        self.fetch_btn = ttk.Button(input_frame, text="Fetch Data", command=self.fetch_data_thread)
        self.fetch_btn.grid(row=0, column=10, padx=10, pady=5, sticky=tk.W)
        
        # Save Button
        self.save_btn = ttk.Button(input_frame, text="Save to JPG", command=self.save_to_jpg, state="disabled")
        self.save_btn.grid(row=0, column=11, padx=10, pady=5, sticky=tk.W)
        
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

        # Precipitation Threshold
        ttk.Label(input_frame, text="Min Precip (mm):").grid(row=2, column=0, padx=5, pady=2, sticky=tk.W)
        self.precip_threshold_var = tk.DoubleVar(value=5.0)
        self.precip_threshold_spin = ttk.Spinbox(input_frame, from_=0, to=50, increment=0.5,
                                                  textvariable=self.precip_threshold_var, width=6)
        self.precip_threshold_spin.grid(row=2, column=1, padx=5, pady=2, sticky=tk.W)

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

    def _on_location_changed(self, event=None):
        if self.location_var.get() == "Custom...":
            self.location_cb.grid_remove()
            self.custom_city_entry.grid()
            self.custom_city_entry.focus_set()

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
            messagebox.showerror("Error", "Please enter a city or location name.")
            return

        self.fetch_btn.config(state="disabled")
        self.save_btn.config(state="disabled")
        self.status_var.set("Fetching coordinates...")
        self.tree.delete(*self.tree.get_children())
        if self.canvas_widget:
            self.canvas_widget.get_tk_widget().destroy()
            self.canvas_widget = None
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
            # Fetch one extra year to cover cross-year seasons (e.g. Dec-Feb summer)
            start_date = f"{start_year - 1}-01-01"
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

            fig = create_visualization_figure(processed_df, city, display_period, units, monthly, unify_scales)

            self._last_city = city
            self._last_period = display_period
            self._last_depth = depth

            self.root.after(0, self.update_ui, processed_df, fig, units)
            
        except Exception as e:
            logger.error("Error during data fetch/processing", exc_info=True)
            self.root.after(0, self.show_error, str(e))

    def update_ui(self, df, fig, units):
        self.current_fig = fig
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

        self.status_var.set("Ready.")
        self.fetch_btn.config(state="normal")
        self.save_btn.config(state="normal")
        
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
                    messagebox.showinfo("Success", f"Chart saved successfully to:\n{filepath}")
                except Exception as e:
                    logger.error("Failed to save chart to %s", filepath, exc_info=True)
                    messagebox.showerror("Error", f"Failed to save image:\n{e}")
        
    def show_error(self, message):
        messagebox.showerror("Error", message)
        self.status_var.set("Error occurred.")
        self.fetch_btn.config(state="normal")
        self.save_btn.config(state="disabled")

if __name__ == "__main__":
    setup_logging()
    logger.info("Weather Juice UI starting")
    root = tk.Tk()
    app = WeatherJuiceApp(root)
    root.mainloop()
