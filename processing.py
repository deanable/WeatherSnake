import pandas as pd
from typing import Dict, Any

def get_season_months(period: str) -> tuple[int, int]:
    """Returns the start and end month for a given season."""
    p = period.lower()
    if p == "summer":
        return 12, 2
    elif p == "autumn":
        return 3, 5
    elif p == "winter":
        return 6, 8
    elif p == "spring":
        return 9, 11
    elif p == "full year":
        return 1, 12
    else:
        raise ValueError(f"Unknown period: {period}")

def is_date_in_season(date: pd.Timestamp, start_month: int, end_month: int) -> bool:
    """Helper function to determine if a date falls within a specified season."""
    month = date.month
    if start_month <= end_month:
        return start_month <= month <= end_month
    else:
        return month >= start_month or month <= end_month

def process_weather_data(raw_data: Dict[str, Any], period: str, units: str, monthly: bool) -> pd.DataFrame:
    """Processes raw API data into seasonal averages over the specified lookback depth."""
    
    daily_data = raw_data.get("daily", {})
    if not daily_data:
        raise ValueError("No daily data found in API response.")
        
    df = pd.DataFrame({
        "date": pd.to_datetime(daily_data["time"]),
        "temp_max": daily_data["temperature_2m_max"],
        "temp_min": daily_data["temperature_2m_min"],
        "precip_sum": daily_data["precipitation_sum"],
    })

    start_month, end_month = get_season_months(period)
    df["in_season"] = df["date"].apply(lambda d: is_date_in_season(d, start_month, end_month))
    df = df[df["in_season"]].copy()
    
    if monthly:
        df["month"] = df["date"].dt.month
        grouped = df.groupby("month")[["temp_max", "temp_min", "precip_sum"]].mean().reset_index()
        grouped["sort_key"] = grouped["month"].apply(lambda m: m if m >= start_month else m + 12)
        grouped = grouped.sort_values("sort_key").drop(columns=["sort_key"])
        grouped["date_label"] = pd.to_datetime(grouped["month"], format="%m").dt.month_name()
    else:
        df["mm_dd"] = df["date"].dt.strftime("%m-%d")
        grouped = df.groupby("mm_dd")[["temp_max", "temp_min", "precip_sum"]].mean().reset_index()
        
        def get_sort_key(mm_dd):
            m = int(mm_dd.split("-")[0])
            if start_month > end_month and m >= start_month:
                return f"0000-{mm_dd}" 
            else:
                return f"0001-{mm_dd}"
        
        grouped["sort_key"] = grouped["mm_dd"].apply(get_sort_key)
        grouped = grouped.sort_values("sort_key").drop(columns=["sort_key"])
        grouped["date_label"] = grouped["mm_dd"]
        
    if units == "imperial":
        grouped["temp_max"] = (grouped["temp_max"] * 9/5) + 32
        grouped["temp_min"] = (grouped["temp_min"] * 9/5) + 32
        grouped["precip_sum"] = grouped["precip_sum"] / 25.4
        
    result = grouped[["date_label", "temp_max", "temp_min", "precip_sum"]]
    
    return result
