import os
import re
import sys
import pandas as pd
import matplotlib
from matplotlib.figure import Figure
from matplotlib.image import imread


def _asset_path():
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, "assets")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


LOGO_PATH = os.path.join(_asset_path(), "logo.png")


def _safe_filename(name: str) -> str:
    """Sanitize a string for use in a filename."""
    return re.sub(r'[^\w\-]', '_', name)

def print_summary(df: pd.DataFrame, city: str, period: str, units: str):
    """Prints a summary table of the processed weather data to the console."""
    temp_unit = "°F" if units == "imperial" else "°C"
    precip_unit = "inch" if units == "imperial" else "mm"

    print(f"\nWeather Summary for {city} ({period})")
    print("-" * 60)
    print(f"{'Date':<15} | {'Max Temp':<10} | {'Min Temp':<10} | {'Precipitation':<15}")
    print("-" * 60)
    for _, row in df.iterrows():
        print(f"{row['date_label']:<15} | {row['temp_max']:<6.1f} {temp_unit} | {row['temp_min']:<6.1f} {temp_unit} | {row['precip_sum']:<6.1f} {precip_unit}")
    print("-" * 60)

def export_to_csv(df: pd.DataFrame, city: str, period: str):
    """Exports the processed data to a CSV file."""
    filename = f"weather_report_{_safe_filename(city)}_{_safe_filename(period)}.csv"
    df.to_csv(filename, index=False)
    print(f"Exported data to {filename}")

def generate_visualizations(df: pd.DataFrame, city: str, period: str, units: str, monthly: bool, unify_scales: bool = True):
    """Generates and saves temperature and rainfall graphs as a PNG file."""
    fig = create_visualization_figure(df, city, period, units, monthly, unify_scales)
    filename = f"weather_plot_{_safe_filename(city)}_{_safe_filename(period)}.png"
    fig.savefig(filename)
    print(f"Saved visualization to {filename}")

def create_visualization_figure(df: pd.DataFrame, city: str, period: str, units: str, monthly: bool, unify_scales: bool = True):
    """Creates a matplotlib Figure for the weather data (useful for UI embedding).

    Uses Figure() directly instead of plt.subplots() to avoid Tk event loop
    conflicts when called from a background thread.
    """
    temp_unit = "°F" if units == "imperial" else "°C"
    precip_unit = "inch" if units == "imperial" else "mm"

    fig = Figure(figsize=(10, 6))
    ax1 = fig.add_subplot(111)

    ax1.set_xlabel('Date' if not monthly else 'Month')
    ax1.set_ylabel(f'Temperature ({temp_unit})', color='tab:red')
    ax1.plot(df['date_label'], df['temp_max'], color='tab:red', label='Max Temp', marker='o')
    ax1.plot(df['date_label'], df['temp_min'], color='tab:orange', label='Min Temp', marker='x')
    ax1.tick_params(axis='y', labelcolor='tab:red')

    if not monthly and len(df) > 15:
        ax1.tick_params(axis='x', rotation=90)
    else:
        ax1.tick_params(axis='x', rotation=45)

    ax2 = ax1.twinx()
    ax2.set_ylabel(f'Precipitation ({precip_unit})', color='tab:blue')
    ax2.bar(df['date_label'], df['precip_sum'], color='tab:blue', alpha=0.3, label='Rainfall')
    ax2.tick_params(axis='y', labelcolor='tab:blue')

    if unify_scales:
        min_val = min(df['temp_min'].min(), df['precip_sum'].min())
        max_val = max(df['temp_max'].max(), df['precip_sum'].max())
        padding = (max_val - min_val) * 0.05 if max_val != min_val else 1.0

        ax1.set_ylim(min_val - padding, max_val + padding)
        ax2.set_ylim(min_val - padding, max_val + padding)

    lines_1, labels_1 = ax1.get_legend_handles_labels()
    lines_2, labels_2 = ax2.get_legend_handles_labels()
    ax1.legend(lines_1 + lines_2, labels_1 + labels_2, loc='upper left')

    ax1.set_title(f"Historical Weather for {city} ({period})")

    # Watermark logo in bottom-left corner
    if os.path.isfile(LOGO_PATH):
        logo = imread(LOGO_PATH)
        # Place a small axes in the bottom-left for the watermark
        logo_ax = fig.add_axes([0.01, 0.01, 0.04, 0.04])
        logo_ax.imshow(logo)
        logo_ax.set_axis_off()

    fig.tight_layout()

    return fig
