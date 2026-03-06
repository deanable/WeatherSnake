import argparse
from datetime import datetime
from api_client import get_coordinates, fetch_historical_weather
from processing import process_weather_data
from output import print_summary, export_to_csv, generate_visualizations

def main():
    parser = argparse.ArgumentParser(description="Weather Juice - Historical weather averages and visualizations.")
    parser.add_argument("--city", type=str, required=True, help="Name of the location.")
    parser.add_argument("--period", type=str, choices=["Summer", "Autumn", "Winter", "Spring", "Full Year"], required=True, help="Season or full year.")
    parser.add_argument("--depth", type=int, choices=[1, 5, 10, 20], required=True, help="Analysis depth in years (1, 5, 10, or 20).")
    parser.add_argument("--units", type=str, choices=["metric", "imperial"], default="metric", help="Unit system: metric or imperial.")
    parser.add_argument("--monthly", action="store_true", help="Toggle monthly-only averages.")
    
    args = parser.parse_args()
    
    print(f"Fetching data for {args.city}...")
    
    try:
        lat, lon = get_coordinates(args.city)
        print(f"Found coordinates: Lat {lat:.4f}, Lon {lon:.4f}")
    except Exception as e:
        print(f"Error getting coordinates: {e}")
        return
    
    current_year = datetime.now().year
    end_year = current_year - 1
    start_year = end_year - args.depth + 1
    
    start_date = f"{start_year - 1}-01-01"
    end_date = f"{end_year}-12-31"
    
    print(f"Fetching historical data from {start_date} to {end_date}...")
    
    try:
        raw_data = fetch_historical_weather(lat, lon, start_date, end_date)
    except Exception as e:
        print(f"Error fetching historical data: {e}")
        return
        
    print("Processing data...")
    try:
        processed_df = process_weather_data(raw_data, args.period, args.units, args.monthly)
    except Exception as e:
        print(f"Error processing data: {e}")
        return
        
    if processed_df.empty:
        print("No valid data found for the selected parameters.")
        return
    
    print_summary(processed_df, args.city, args.period, args.units)
    export_to_csv(processed_df, args.city, args.period)
    generate_visualizations(processed_df, args.city, args.period, args.units, args.monthly)

if __name__ == "__main__":
    main()
