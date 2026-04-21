import argparse
import logging
from datetime import datetime

from logger_setup import setup_logging
from api_client import get_coordinates, fetch_historical_weather
from processing import process_weather_data, custom_range_days
from output import print_summary, export_to_csv, generate_visualizations

logger = logging.getLogger(__name__)

def main():
    setup_logging()
    parser = argparse.ArgumentParser(description="Weather Juice - Historical weather averages and visualizations.")
    parser.add_argument("--city", type=str, required=True, help="Location name or preset (Cape Town, Johannesburg, Durban).")
    parser.add_argument("--period", type=str, choices=["Summer", "Autumn", "Winter", "Spring", "Full Year"], default=None, help="Season or full year.")
    parser.add_argument("--depth", type=int, choices=[1, 5, 10, 20], default=None, help="Analysis depth in years (1, 5, 10, or 20).")
    parser.add_argument("--units", type=str, choices=["metric", "imperial"], default="metric", help="Unit system: metric or imperial.")
    parser.add_argument("--monthly", action="store_true", help="Toggle monthly-only averages.")
    parser.add_argument("--unify-scales", action="store_true", help="Unify the temperature and precipitation Y-axis scales.")
    parser.add_argument("--start-day", type=int, default=None, help="Custom range start day (1-31). Requires --start-month, --end-day, --end-month, --depth.")
    parser.add_argument("--start-month", type=int, default=None, help="Custom range start month (1-12).")
    parser.add_argument("--end-day", type=int, default=None, help="Custom range end day (1-31).")
    parser.add_argument("--end-month", type=int, default=None, help="Custom range end month (1-12).")

    args = parser.parse_args()

    # Determine mode: custom range or season-based
    cr_args = [args.start_day, args.start_month, args.end_day, args.end_month]
    if any(a is not None for a in cr_args):
        if not all(a is not None for a in cr_args):
            parser.error("--start-day, --start-month, --end-day, --end-month must all be provided together.")
        if not args.depth:
            parser.error("--depth is required for custom range.")
        custom_start = (args.start_month, args.start_day)
        custom_end = (args.end_month, args.end_day)
        span = custom_range_days(*custom_start, *custom_end)  # noqa: E501
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
    # Fetch one extra year before the range to cover cross-year seasons (e.g. Dec-Feb summer)
    start_date = f"{start_year - 1}-01-01"
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
                                            custom_start=custom_start, custom_end=custom_end)
    except Exception as e:
        logger.error("Failed to process weather data", exc_info=True)
        print(f"Error processing data: {e}")
        return

    if processed_df.empty:
        print("No valid data found for the selected parameters.")
        return

    print_summary(processed_df, args.city, period, args.units)
    export_to_csv(processed_df, args.city, period)
    generate_visualizations(processed_df, args.city, period, args.units, monthly, args.unify_scales)

if __name__ == "__main__":
    main()
