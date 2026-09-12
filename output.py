import logging
import os
import re
import sys
import pandas as pd
import matplotlib
from matplotlib.figure import Figure
from matplotlib.image import imread

from chart_theme import PALETTE, apply_mpl_theme

logger = logging.getLogger(__name__)


def _asset_path():
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, "assets")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


LOGO_PATH = os.path.join(_asset_path(), "logo.png")


def _safe_filename(name: str) -> str:
    """Sanitize a string for use in a filename."""
    return re.sub(r'[^\w\-]', '_', name)


def temp_unit(units: str) -> str:
    """Display unit for temperatures (°C or °F)."""
    return "°F" if units == "imperial" else "°C"


def precip_unit(units: str) -> str:
    """Display unit for precipitation (inch or mm)."""
    return "inch" if units == "imperial" else "mm"


def _fmt_temp(celsius: float, units: str) -> str:
    """Format a metric temperature for display, converting for imperial."""
    if units == "imperial":
        celsius = (celsius * 9 / 5) + 32
    return f"{celsius:.1f}{temp_unit(units)}"


def _fmt_temp_delta(delta_celsius: float, units: str) -> str:
    """Format a temperature *difference*, converting for imperial."""
    if units == "imperial":
        delta_celsius = delta_celsius * 9 / 5
    return f"{delta_celsius:+.1f}{temp_unit(units)}"


def _fmt_precip(mm: float, units: str) -> str:
    """Format a metric precipitation amount for display, converting for imperial."""
    if units == "imperial":
        mm = mm / 25.4
    return f"{mm:.1f} {precip_unit(units)}"


def _fmt_precip_delta(delta_mm: float, units: str) -> str:
    """Format a precipitation *difference*, converting for imperial."""
    if units == "imperial":
        delta_mm = delta_mm / 25.4
    return f"{delta_mm:+.1f} {precip_unit(units)}"


def format_summary(df: pd.DataFrame, city: str, period: str, units: str) -> str:
    """Build the plain summary table of the processed weather data."""
    tu, pu = temp_unit(units), precip_unit(units)
    lines = [
        "",
        f"Weather Summary for {city} ({period})",
        "-" * 60,
        f"{'Date':<15} | {'Max Temp':<10} | {'Min Temp':<10} | {'Precipitation':<15}",
        "-" * 60,
    ]
    for _, row in df.iterrows():
        precip = row.get('precip_sum', row.get('precip_in', 0.0))
        lines.append(
            f"{row['date_label']:<15} | {row['temp_max']:<6.1f} {tu} | "
            f"{row['temp_min']:<6.1f} {tu} | {precip:<6.1f} {pu}"
        )
    lines.append("-" * 60)
    return "\n".join(lines)


def print_summary(df: pd.DataFrame, city: str, period: str, units: str):
    """Print the summary table of the processed weather data."""
    print(format_summary(df, city, period, units))


def format_conditions_summary(conditions: dict, units: str) -> str:
    """Build the most-common-condition distribution text."""
    lines = ["", "Weather Conditions (historical)", "-" * 60]
    for _, row in conditions["conditions"].iterrows():
        lines.append(f"  {row['condition']:<22} {int(row['days']):>5} days   {row['share'] * 100:>5.1f}%")
    rain_pct = conditions["rainy_day_share"] * 100
    lines.append("-" * 60)
    lines.append(f"  Rain days (>=1 mm): {rain_pct:.1f}% of days")
    return "\n".join(lines)


def print_conditions_summary(conditions: dict, units: str):
    """Print the most-common-condition distribution for the window."""
    print(format_conditions_summary(conditions, units))


def format_variability_summary(stats: dict, units: str) -> str:
    """Build typical ranges, extremes, and precipitation variability text."""
    tm, tn = stats["temp_max"], stats["temp_min"]
    lines = [
        "",
        "Variability & Extremes",
        "-" * 60,
        f"  Typical daily high: {_fmt_temp(tm['mean'], units)} "
        f"(range usually {_fmt_temp(tm['p05'], units)} to {_fmt_temp(tm['p95'], units)})",
        f"  Typical daily low:  {_fmt_temp(tn['mean'], units)} "
        f"(range usually {_fmt_temp(tn['p05'], units)} to {_fmt_temp(tn['p95'], units)})",
        f"  Record low/high in window: {_fmt_temp(tn['min'], units)} / {_fmt_temp(tm['max'], units)}",
        "",
        f"  Mean season total precipitation: {_fmt_precip(stats['precip']['mean_year_total'], units)}",
    ]
    wet_year, wet_amt = stats["precip"]["wettest_year"]
    dry_year, dry_amt = stats["precip"]["driest_year"]
    lines.append(f"  Wettest year:  {wet_year} ({_fmt_precip(wet_amt, units)})")
    lines.append(f"  Driest year:   {dry_year} ({_fmt_precip(dry_amt, units)})")
    lines.append(f"  Years above average: {stats['precip']['years_above_mean']} of {stats['years_analyzed']}")
    lines.append(f"  Rain days per year: {stats['rain_days']['mean_per_year']:.0f} avg "
                 f"(max {stats['rain_days']['max_per_year']})")
    return "\n".join(lines)


def print_variability_summary(stats: dict, units: str):
    """Print typical ranges, extremes, and precipitation variability."""
    print(format_variability_summary(stats, units))


def format_yoy_summary(yoy: dict, units: str) -> str:
    """Build per-year window means and trend-per-decade text."""
    table: pd.DataFrame = yoy["table"]
    lines = [
        "",
        "Year-over-Year",
        "-" * 60,
        f"{'Year':<7} | {'Avg High':<12} | {'Avg Low':<12} | {'Precip Total':<14}",
    ]
    for _, row in table.iterrows():
        lines.append(
            f"{int(row['year']):<7} | {_fmt_temp(row['temp_max'], units):<12} | "
            f"{_fmt_temp(row['temp_min'], units):<12} | {_fmt_precip(row['precip_total'], units):<14}"
        )
    lines.append("-" * 60)

    def _trend_line(label, value):
        if value is None:
            return f"  {label}: not enough years"
        direction = "up" if value > 0 else "down"
        return f"  {label}: {value:+.2f} per decade ({direction})"

    lines.append(_trend_line("Avg high trend", yoy["temp_max_trend"]))
    lines.append(_trend_line("Avg low trend", yoy["temp_min_trend"]))
    lines.append(_trend_line("Precip trend", yoy["precip_trend"]))
    return "\n".join(lines)


def print_yoy_summary(yoy: dict, units: str):
    """Print per-year window means and a trend-per-decade estimate."""
    print(format_yoy_summary(yoy, units))


def format_depth_comparison(comparison: dict, units: str) -> str:
    """Build recent-years vs baseline-years comparison text."""
    r, b, d = comparison["recent"], comparison["baseline"], comparison["delta"]
    recent_span = f"{comparison['recent_years'][0]}-{comparison['recent_years'][-1]}"
    baseline_span = f"{comparison['baseline_years'][0]}-{comparison['baseline_years'][-1]}"
    lines = [
        "",
        "Recent vs Baseline",
        "-" * 60,
        f"  {'Metric':<16} {'Recent':<18} {'Baseline':<18} {'Change':<14}",
        f"  {'Avg high':<16} {_fmt_temp(r['temp_max'], units):<18} "
        f"{_fmt_temp(b['temp_max'], units):<18} {_fmt_temp_delta(d['temp_max'], units)}",
        f"  {'Avg low':<16} {_fmt_temp(r['temp_min'], units):<18} "
        f"{_fmt_temp(b['temp_min'], units):<18} {_fmt_temp_delta(d['temp_min'], units)}",
        f"  {'Precip total':<16} {_fmt_precip(r['precip_total'], units):<18} "
        f"{_fmt_precip(b['precip_total'], units):<18} {_fmt_precip_delta(d['precip_total'], units)}",
        "-" * 60,
        f"  Recent window: {recent_span} | Baseline: {baseline_span}",
    ]
    return "\n".join(lines)


def print_depth_comparison(comparison: dict, units: str):
    """Print recent-years vs baseline-years comparison."""
    print(format_depth_comparison(comparison, units))


def build_insights_text(raw_data: dict, period: str, custom_start, custom_end, units: str,
                        show_insights: bool = True, show_yearly: bool = False,
                        precip_threshold: float = 0.0, max_years: int = None) -> str:
    """Build the conditions/variability/yearly text for GUI display.

    Best-effort: sections that fail are logged and skipped.
    """
    from conditions import compute_condition_distribution
    from stats import compute_variability_stats, compute_year_over_year

    sections = []
    if show_insights:
        try:
            conditions = compute_condition_distribution(raw_data, period, custom_start, custom_end)
            if conditions:
                sections.append(format_conditions_summary(conditions, units))
        except Exception:
            logger.warning("Condition summary failed", exc_info=True)
        try:
            stats = compute_variability_stats(raw_data, period, custom_start, custom_end,
                                              precip_threshold=precip_threshold, max_years=max_years)
            sections.append(format_variability_summary(stats, units))
        except Exception:
            logger.warning("Variability summary failed", exc_info=True)
    if show_yearly:
        try:
            yoy = compute_year_over_year(raw_data, period, custom_start, custom_end,
                                         precip_threshold=precip_threshold, max_years=max_years)
            sections.append(format_yoy_summary(yoy, units))
        except Exception:
            logger.warning("Year-over-year summary failed", exc_info=True)
    return "\n".join(sections)


def export_to_csv(df: pd.DataFrame, city: str, period: str):
    """Exports the processed data to a CSV file."""
    filename = f"weather_report_{_safe_filename(city)}_{_safe_filename(period)}.csv"
    df.to_csv(filename, index=False)
    print(f"Exported data to {filename}")
    return filename

def generate_visualizations(df: pd.DataFrame, city: str, period: str, units: str, monthly: bool, unify_scales: bool = True):
    """Generates and saves temperature and rainfall graphs as a PNG file."""
    fig = create_visualization_figure(df, city, period, units, monthly, unify_scales)
    filename = f"weather_plot_{_safe_filename(city)}_{_safe_filename(period)}.png"
    fig.savefig(filename)
    print(f"Saved visualization to {filename}")
    return filename

def create_visualization_figure(df: pd.DataFrame, city: str, period: str, units: str, monthly: bool, unify_scales: bool = True):
    """Creates a themed matplotlib Figure for the weather data.

    Uses Figure() directly instead of plt.subplots() to avoid Tk event loop
    conflicts when called from a background thread. Styling comes from
    chart_theme so the figure matches the GUI and the QuickChart renderer.
    """
    apply_mpl_theme()

    tu = temp_unit(units)
    pu = precip_unit(units)

    fig = Figure(figsize=(10, 6), layout="constrained")
    ax1 = fig.add_subplot(111)

    ax1.set_xlabel('Date' if not monthly else 'Month')
    ax1.set_ylabel(f'Temperature ({tu})')

    # Temperature band between the daily max and min, then the two lines on
    # top of it (weather-approve warm/cool pairing from the palette).
    ax1.fill_between(df['date_label'], df['temp_min'], df['temp_max'],
                     color=PALETTE['temp_warm'], alpha=0.08, linewidth=0)
    ax1.plot(df['date_label'], df['temp_max'], color=PALETTE['temp_warm'],
             label='Max Temp', marker='o', markersize=4, zorder=3)
    ax1.plot(df['date_label'], df['temp_min'], color=PALETTE['temp_cool'],
             label='Min Temp', marker='x', markersize=4, zorder=3)

    if not monthly and len(df) > 15:
        ax1.tick_params(axis='x', rotation=90)
    else:
        ax1.tick_params(axis='x', rotation=45)

    ax2 = ax1.twinx()
    ax2.set_ylabel(f'Precipitation ({pu})')
    ax2.bar(df['date_label'], df['precip_sum'], color=PALETTE['precipitation'],
            alpha=0.45, label='Rainfall', zorder=1)

    # Draw the temperature lines above the precipitation bars: the twin axis
    # would otherwise paint its bars over ax1's artists.
    ax1.set_zorder(ax2.get_zorder() + 1)
    ax1.patch.set_visible(False)

    # Twin axes re-enable the right spine; keep it subtle and match the left.
    for spine in ('left', 'right', 'bottom'):
        ax2.spines[spine].set_visible(spine == 'right')
        ax2.spines[spine].set_color(PALETTE['divider'])

    # Horizontal grid only, drawn under the data; skip ax2 to avoid double
    # rules from the twin axis.
    ax1.grid(axis='y', color=PALETTE['divider'], linewidth=0.8, alpha=0.9)
    ax1.set_axisbelow(True)
    ax2.grid(False)

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
    # Watermark logo in bottom-left corner (add_axes figures are excluded
    # from the constrained-layout manager, so it stays pinned).
    if os.path.isfile(LOGO_PATH):
        logo = imread(LOGO_PATH)
        logo_ax = fig.add_axes([0.01, 0.01, 0.04, 0.04])
        logo_ax.imshow(logo)
        logo_ax.set_axis_off()

    return fig
