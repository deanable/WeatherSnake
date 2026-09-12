import argparse
import logging
from datetime import datetime

from logger_setup import setup_logging
from api_client import get_coordinates, fetch_historical_weather
from processing import process_weather_data, custom_range_days, get_season_months
from conditions import compute_condition_distribution
from stats import compute_variability_stats, compute_year_over_year, compare_depths
from output import (
    print_summary, export_to_csv, generate_visualizations,
    print_conditions_summary, print_variability_summary,
    print_yoy_summary, print_depth_comparison,
)

logger = logging.getLogger(__name__)

PRESETS = ["Cape Town", "Johannesburg", "Durban"]


def main():
    setup_logging()
    parser = argparse.ArgumentParser(
        description="Weather Juice - Historical weather averages, conditions, and trend insights.",
        epilog=(
            "Examples:\n"
            "  python weather_juice.py --city \"Cape Town\" --period Summer --depth 10 --units metric\n"
            "  python weather_juice.py --city Johannesburg --period Winter --depth 5 --units imperial\n"
            "  python weather_juice.py --city \"Durban\" --start-day 15 --start-month 11 --end-day 28 --end-month 2 --depth 10\n"
            "  python weather_juice.py --city Durban --period Summer --depth 20 --yearly --compare-recent 3\n"
            "  python weather_juice.py --list-presets\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--city",
        type=str,
        default=None,
        help="Location name or preset (Cape Town, Johannesburg, Durban).",
    )
    parser.add_argument(
        "--period",
        type=str,
        choices=["Summer", "Autumn", "Winter", "Spring", "Full Year"],
        default=None,
        help="Season or full year. Required when not using a custom range.",
    )
    parser.add_argument(
        "--depth",
        type=int,
        choices=[1, 3, 5, 7, 10, 15, 20],
        default=None,
        help="Analysis depth in years (1, 3, 5, 7, 10, 15, or 20).",
    )
    parser.add_argument(
        "--units",
        type=str,
        choices=["metric", "imperial"],
        default="metric",
        help="Unit system: metric (°C, mm) or imperial (°F, inch).",
    )
    parser.add_argument(
        "--monthly",
        action="store_true",
        help="Toggle monthly-only averages.",
    )
    parser.add_argument(
        "--unify-scales",
        action="store_true",
        help="Unify the temperature and precipitation Y-axis scales.",
    )
    parser.add_argument(
        "--precip-threshold",
        type=float,
        default=0.0,
        metavar="MM",
        help="Zero out daily precipitation below this many mm to exclude dew/frost (default: off).",
    )
    parser.add_argument(
        "--start-day",
        type=int,
        default=None,
        help="Custom range start day (1-31). Requires --start-month, --end-day, --end-month, --depth.",
    )
    parser.add_argument(
        "--start-month",
        type=int,
        default=None,
        help="Custom range start month (1-12).",
    )
    parser.add_argument(
        "--end-day",
        type=int,
        default=None,
        help="Custom range end day (1-31).",
    )
    parser.add_argument(
        "--end-month",
        type=int,
        default=None,
        help="Custom range end month (1-12).",
    )
    parser.add_argument(
        "--no-insights",
        action="store_true",
        help="Skip the condition and variability/extremes summaries.",
    )
    parser.add_argument(
        "--yearly",
        action="store_true",
        help="Show a year-by-year breakdown with trend-per-decade estimates.",
    )
    parser.add_argument(
        "--compare-recent",
        type=int,
        default=None,
        metavar="N",
        help="Compare the most recent N years against a baseline (needs --depth >= N + baseline).",
    )
    parser.add_argument(
        "--compare-baseline",
        type=int,
        default=10,
        metavar="M",
        help="Baseline depth in years for --compare-recent (default 10).",
    )
    parser.add_argument(
        "--list-presets",
        action="store_true",
        help="Show the built-in city list and exit.",
    )

    args = parser.parse_args()

    if args.list_presets:
        print("Built-in location presets:")
        for c in PRESETS:
            print(f"  - {c}")
        return

    if not args.city:
        parser.error("--city is required (or use --list-presets).")

    # Determine mode: custom range or season-based
    cr_args = [args.start_day, args.start_month, args.end_day, args.end_month]
    if any(a is not None for a in cr_args):
        if not all(a is not None for a in cr_args):
            parser.error("--start-day, --start-month, --end-day, --end-month must all be provided together.")
        if not args.depth:
            parser.error("--depth is required for custom range.")
        custom_start = (args.start_month, args.start_day)
        custom_end = (args.end_month, args.end_day)
        span = custom_range_days(*custom_start, *custom_end)
        monthly = span > 31
        month_names = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
                       7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}
        period = f"Custom: {args.start_day} {month_names[args.start_month]} - {args.end_day} {month_names[args.end_month]}"
    else:
        if not args.period:
            parser.error("--period is required when not using custom range.")
        if not args.depth:
            parser.error("--depth is required.")
        custom_start = None
        custom_end = None
        monthly = args.monthly
        period = args.period

    is_custom = custom_start is not None
    logger.info("CLI started: city=%s, period=%s, custom=%s", args.city, period, is_custom)
    print(f"Fetching data for {args.city}...")

    try:
        lat, lon = get_coordinates(args.city)
        print(f"Found coordinates: Lat {lat:.4f}, Lon {lon:.4f}")
    except Exception as e:
        logger.error("Failed to get coordinates for '%s'", args.city, exc_info=True)
        print(f"Error getting coordinates: {e}")
        return

    current_year = datetime.now().year
    end_year = current_year - 1
    start_year = end_year - args.depth + 1
    # Cross-year windows (e.g. Dec-Feb summer) need one extra leading year so
    # the earliest occurrence includes its head month; within-year windows do not.
    if is_custom:
        extra_year = custom_start[0] > custom_end[0]
    else:
        window_start_month, window_end_month = get_season_months(period)
        extra_year = window_start_month > window_end_month
    start_date = f"{start_year - 1 if extra_year else start_year}-01-01"
    end_date = f"{end_year}-12-31"

    print(f"Fetching historical data from {start_date} to {end_date}...")

    try:
        raw_data = fetch_historical_weather(lat, lon, start_date, end_date)
    except Exception as e:
        logger.error("Failed to fetch historical data (%s to %s)", start_date, end_date, exc_info=True)
        print(f"Error fetching historical data: {e}")
        return

    print("Processing data...")
    try:
        processed_df = process_weather_data(raw_data, period, args.units, monthly,
                                            custom_start=custom_start, custom_end=custom_end,
                                            precip_threshold=args.precip_threshold)
    except Exception as e:
        logger.error("Failed to process weather data", exc_info=True)
        print(f"Error processing data: {e}")
        return

    if processed_df.empty:
        print("No valid data found for the selected parameters.")
        return

    print_summary(processed_df, args.city, period, args.units)

    if not args.no_insights:
        try:
            conditions = compute_condition_distribution(raw_data, period, custom_start, custom_end)
            if conditions:
                print_conditions_summary(conditions, args.units)
        except Exception as e:
            logger.warning("Condition summary failed: %s", e)
        try:
            stats = compute_variability_stats(raw_data, period, custom_start, custom_end,
                                              precip_threshold=args.precip_threshold,
                                              max_years=args.depth)
            print_variability_summary(stats, args.units)
        except Exception as e:
            logger.warning("Variability summary failed: %s", e)

    if args.yearly:
        try:
            yoy = compute_year_over_year(raw_data, period, custom_start, custom_end,
                                         precip_threshold=args.precip_threshold,
                                         max_years=args.depth)
            print_yoy_summary(yoy, args.units)
        except Exception as e:
            logger.warning("Year-over-year summary failed: %s", e)

    if args.compare_recent:
        try:
            comparison = compare_depths(raw_data, period, args.compare_recent,
                                        args.compare_baseline, custom_start, custom_end,
                                        precip_threshold=args.precip_threshold)
            print_depth_comparison(comparison, args.units)
        except Exception as e:
            logger.warning("Depth comparison failed: %s", e)
            print(f"Comparison skipped: {e}")

    export_to_csv(processed_df, args.city, period)
    generate_visualizations(processed_df, args.city, period, args.units, monthly, args.unify_scales)


if __name__ == "__main__":
    main()
