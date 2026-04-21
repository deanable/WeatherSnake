import logging
import pandas as pd
from typing import Dict, Any

logger = logging.getLogger(__name__)

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
        logger.error("Unknown period requested: %s", period)
        raise ValueError(f"Unknown period: {period}")

def is_date_in_season(date: pd.Timestamp, start_month: int, end_month: int) -> bool:
    """Helper function to determine if a date falls within a specified season."""
    month = date.month
    if start_month <= end_month:
        return start_month <= month <= end_month
    else:
        return month >= start_month or month <= end_month

def is_date_in_custom_range(date: pd.Timestamp, start_month: int, start_day: int, end_month: int, end_day: int) -> bool:
    """Check if a date's month/day falls within a custom day/month window, handling cross-year wrapping."""
    if date.month == 2 and date.day == 29:
        return False
    md = (date.month, date.day)
    start = (start_month, start_day)
    end = (end_month, end_day)
    if start <= end:
        return start <= md <= end
    else:
        # Cross-year range (e.g., Dec 1 to Feb 28)
        return md >= start or md <= end

def custom_range_days(start_month: int, start_day: int, end_month: int, end_day: int) -> int:
    """Estimate the number of days in a custom day/month range."""
    from datetime import date
    # Use a non-leap year as reference
    start = date(2001, start_month, min(start_day, 28))
    end = date(2001, end_month, min(end_day, 28))
    if start <= end:
        return (end - start).days
    else:
        # Cross-year: days from start to Dec 31 + days from Jan 1 to end
        return (date(2001, 12, 31) - start).days + (end - date(2001, 1, 1)).days + 1

def process_weather_data(raw_data: Dict[str, Any], period: str, units: str, monthly: bool,
                         custom_start: tuple = None, custom_end: tuple = None,
                         precip_threshold: float = 0.0) -> pd.DataFrame:
    """Processes raw API data into seasonal averages over the specified lookback depth.

    For custom ranges, pass custom_start=(month, day) and custom_end=(month, day).
    The monthly flag is auto-determined from range span when custom range is used.
    precip_threshold: values below this (mm) are zeroed out to exclude dew.
    """

    is_custom = custom_start is not None and custom_end is not None
    logger.debug("Processing weather data: period=%s, units=%s, monthly=%s, custom=%s", period, units, monthly, is_custom)

    daily_data = raw_data.get("daily", {})
    if not daily_data:
        logger.error("No daily data found in API response")
        raise ValueError("No daily data found in API response.")

    df = pd.DataFrame({
        "date": pd.to_datetime(daily_data["time"]),
        "temp_max": daily_data["temperature_2m_max"],
        "temp_min": daily_data["temperature_2m_min"],
        "precip_sum": daily_data["precipitation_sum"],
    })
    logger.debug("Raw dataframe: %d rows", len(df))

    # Zero out precipitation below threshold (exclude dew)
    if precip_threshold > 0:
        below = df["precip_sum"] < precip_threshold
        df.loc[below, "precip_sum"] = 0.0
        logger.debug("Zeroed %d precipitation values below %.1f mm threshold", below.sum(), precip_threshold)

    # Exclude leap day (Feb 29) from all calculations
    leap_mask = (df["date"].dt.month == 2) & (df["date"].dt.day == 29)
    if leap_mask.any():
        df = df[~leap_mask].copy()
        logger.debug("Excluded %d leap day rows, %d rows remaining", leap_mask.sum(), len(df))

    if is_custom:
        sm, sd = custom_start
        em, ed = custom_end
        df["in_range"] = df["date"].apply(lambda d: is_date_in_custom_range(d, sm, sd, em, ed))
        df = df[df["in_range"]].copy()
        logger.debug("After custom range filter (%d/%d - %d/%d): %d rows", sm, sd, em, ed, len(df))
        span = custom_range_days(sm, sd, em, ed)
        monthly = span > 31
        start_month = sm
    else:
        start_month, end_month = get_season_months(period)
        df["in_season"] = df["date"].apply(lambda d: is_date_in_season(d, start_month, end_month))
        df = df[df["in_season"]].copy()
        logger.debug("After season filter (%s): %d rows", period, len(df))

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
            if start_month > (end_month if not is_custom else em) and m >= start_month:
                return f"0000-{mm_dd}"
            else:
                return f"0001-{mm_dd}"

        grouped["sort_key"] = grouped["mm_dd"].apply(get_sort_key)
        grouped = grouped.sort_values("sort_key").drop(columns=["sort_key"])
        grouped["date_label"] = grouped["mm_dd"]

    # Apply threshold again after averaging — daily zeroing doesn't guarantee
    # the averaged result stays below threshold when mixing zeroed and non-zeroed days.
    if precip_threshold > 0:
        below = grouped["precip_sum"] < precip_threshold
        grouped.loc[below, "precip_sum"] = 0.0

    if units == "imperial":
        grouped["temp_max"] = (grouped["temp_max"] * 9/5) + 32
        grouped["temp_min"] = (grouped["temp_min"] * 9/5) + 32
        grouped["precip_sum"] = grouped["precip_sum"] / 25.4

    result = grouped[["date_label", "temp_max", "temp_min", "precip_sum"]]
    logger.debug("Processing complete: %d output rows", len(result))

    return result
