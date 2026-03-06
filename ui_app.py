import tkinter as tk
from tkinter import ttk, messagebox
import threading
from datetime import datetime

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from api_client import get_coordinates, fetch_historical_weather
from processing import process_weather_data
from output import create_visualization_figure

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

        # City
        ttk.Label(input_frame, text="City:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.city_var = tk.StringVar(value="Cape Town")
        self.city_entry = ttk.Entry(input_frame, textvariable=self.city_var, width=20)
        self.city_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)

        # Period
        ttk.Label(input_frame, text="Period:").grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)
        self.period_var = tk.StringVar(value="Summer")
        self.period_cb = ttk.Combobox(input_frame, textvariable=self.period_var, values=["Summer", "Autumn", "Winter", "Spring", "Full Year"], state="readonly", width=12)
        self.period_cb.grid(row=0, column=3, padx=5, pady=5, sticky=tk.W)

        # Depth
        ttk.Label(input_frame, text="Depth (Years):").grid(row=0, column=4, padx=5, pady=5, sticky=tk.W)
        self.depth_var = tk.IntVar(value=10)
        self.depth_cb = ttk.Combobox(input_frame, textvariable=self.depth_var, values=[1, 5, 10, 20], state="readonly", width=5)
        self.depth_cb.grid(row=0, column=5, padx=5, pady=5, sticky=tk.W)

        # Units
        ttk.Label(input_frame, text="Units:").grid(row=0, column=6, padx=5, pady=5, sticky=tk.W)
        self.units_var = tk.StringVar(value="metric")
        self.units_cb = ttk.Combobox(input_frame, textvariable=self.units_var, values=["metric", "imperial"], state="readonly", width=10)
        self.units_cb.grid(row=0, column=7, padx=5, pady=5, sticky=tk.W)

        # Monthly Checkbox
        self.monthly_var = tk.BooleanVar(value=True)
        self.monthly_chk = ttk.Checkbutton(input_frame, text="Monthly Average", variable=self.monthly_var)
        self.monthly_chk.grid(row=0, column=8, padx=15, pady=5, sticky=tk.W)

        # Fetch Button
        self.fetch_btn = ttk.Button(input_frame, text="Fetch Data", command=self.fetch_data_thread)
        self.fetch_btn.grid(row=0, column=9, padx=10, pady=5, sticky=tk.W)
        
        # Loading Label
        self.status_var = tk.StringVar(value="Ready.")
        self.status_label = ttk.Label(input_frame, textvariable=self.status_var, foreground="gray")
        self.status_label.grid(row=1, column=0, columnspan=10, sticky=tk.W, padx=5, pady=2)

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

    def fetch_data_thread(self):
        self.fetch_btn.config(state="disabled")
        self.status_var.set("Fetching coordinates...")
        self.tree.delete(*self.tree.get_children())
        if self.canvas_widget:
            self.canvas_widget.get_tk_widget().destroy()
            self.canvas_widget = None
            
        thread = threading.Thread(target=self.process_data)
        thread.daemon = True
        thread.start()

    def process_data(self):
        city = self.city_var.get()
        period = self.period_var.get()
        depth = self.depth_var.get()
        units = self.units_var.get()
        monthly = self.monthly_var.get()
        
        try:
            lat, lon = get_coordinates(city)
            
            self.root.after(0, lambda: self.status_var.set(f"Fetching historical data for {city}..."))
            
            current_year = datetime.now().year
            end_year = current_year - 1
            start_year = end_year - depth + 1
            start_date = f"{start_year - 1}-01-01"
            end_date = f"{end_year}-12-31"
            
            raw_data = fetch_historical_weather(lat, lon, start_date, end_date)
            
            self.root.after(0, lambda: self.status_var.set("Processing and generating chart..."))
            processed_df = process_weather_data(raw_data, period, units, monthly)
            
            if processed_df.empty:
                raise ValueError("No data available for the given timeframe.")
                
            fig = create_visualization_figure(processed_df, city, period, units, monthly)
            
            self.root.after(0, self.update_ui, processed_df, fig, units)
            
        except Exception as e:
            self.root.after(0, self.show_error, str(e))

    def update_ui(self, df, fig, units):
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
        self.canvas_widget = FigureCanvasTkAgg(fig, master=self.canvas_frame)
        self.canvas_widget.draw()
        self.canvas_widget.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.status_var.set("Ready.")
        self.fetch_btn.config(state="normal")
        
    def show_error(self, message):
        messagebox.showerror("Error", message)
        self.status_var.set("Error occurred.")
        self.fetch_btn.config(state="normal")

if __name__ == "__main__":
    root = tk.Tk()
    app = WeatherJuiceApp(root)
    root.mainloop()
