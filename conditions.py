"""Weather-code translation and condition summaries.

Translates Open-Meteo's WMO `weather_code` values into plain-language
conditions and computes "most common condition" distributions over a
season or custom day/month window.
"""
import logging
from typing import Dict, Any, Optional

import pandas as pd

from processing import get_season_months, is_date_in_season, is_date_in_custom_range

logger = logging.getLogger(__name__)

# WMO weather interpretation codes -> plain-language description.
WEATHER_CODE_DESCRIPTIONS: Dict[int, str] = {
	0: "Clear sky",
	1: "Mainly clear",
	2: "Partly cloudy",
	3: "Overcast",
	45: "Fog",
	48: "Depositing rime fog",
	51: "Light drizzle",
	53: "Moderate drizzle",
	55: "Dense drizzle",
	56: "Light freezing drizzle",
	57: "Dense freezing drizzle",
	61: "Slight rain",
	63: "Moderate rain",
	65: "Heavy rain",
	66: "Light freezing rain",
	67: "Heavy freezing rain",
	71: "Slight snowfall",
	73: "Moderate snowfall",
	75: "Heavy snowfall",
	77: "Snow grains",
	80: "Slight rain showers",
	81: "Moderate rain showers",
	82: "Violent rain showers",
	85: "Slight snow showers",
	86: "Heavy snow showers",
	95: "Thunderstorm",
	96: "Thunderstorm with slight hail",
	99: "Thunderstorm with heavy hail",
}

# Coarse buckets used for the "most common condition" distribution.
_CODE_CATEGORY: Dict[int, str] = {
	0: "Clear sky",
	1: "Mainly clear",
	2: "Partly cloudy",
	3: "Overcast",
	45: "Fog",
	48: "Fog",
	51: "Drizzle", 53: "Drizzle", 55: "Drizzle",
	56: "Freezing drizzle", 57: "Freezing drizzle",
	61: "Rain", 63: "Rain", 65: "Rain",
	66: "Freezing rain", 67: "Freezing rain",
	71: "Snow", 73: "Snow", 75: "Snow", 77: "Snow",
	80: "Rain showers", 81: "Rain showers", 82: "Rain showers",
	85: "Snow showers", 86: "Snow showers",
	95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm",
}

# Days with at least this much precipitation (mm) count as "rain days".
RAIN_DAY_MM = 1.0


def describe_weather_code(code: Optional[float]) -> str:
	"""Plain-language description for a WMO weather code."""
	if code is None or (isinstance(code, float) and pd.isna(code)):
		return "Unknown"
	try:
		return WEATHER_CODE_DESCRIPTIONS.get(int(code), f"Code {int(code)}")
	except (TypeError, ValueError):
		return "Unknown"


def weather_code_category(code: Optional[float]) -> str:
	"""Coarse condition category for a WMO weather code."""
	if code is None or (isinstance(code, float) and pd.isna(code)):
		return "Unknown"
	try:
		return _CODE_CATEGORY.get(int(code), f"Code {int(code)}")
	except (TypeError, ValueError):
		return "Unknown"


def compute_condition_distribution(
	raw_data: Dict[str, Any],
	period: str,
	custom_start: tuple = None,
	custom_end: tuple = None,
) -> Optional[Dict[str, Any]]:
	"""Summarizes weather conditions over the requested window.

	Returns None when the API response has no weather_code data.
	Returns a dict with:
	  total_days: number of analyzed days
	  conditions: DataFrame [condition, days, share] sorted most-common first
	  dominant: most common condition label
	  rainy_day_share: fraction of days with >= 1 mm precipitation
	"""
	daily = raw_data.get("daily", {})
	if not daily or "weather_code" not in daily:
		logger.info("No weather_code in API response; skipping condition summary")
		return None

	df = pd.DataFrame({
		"date": pd.to_datetime(daily["time"]),
		"precip_sum": daily.get("precipitation_sum", [None] * len(daily["time"])),
		"code": daily["weather_code"],
	})

	# Drop leap day for consistency with the rest of the pipeline
	leap_mask = (df["date"].dt.month == 2) & (df["date"].dt.day == 29)
	df = df[~leap_mask]

	if custom_start is not None and custom_end is not None:
		sm, sd = custom_start
		em, ed = custom_end
		df = df[df["date"].apply(lambda d: is_date_in_custom_range(d, sm, sd, em, ed))]
	else:
		start_month, end_month = get_season_months(period)
		df = df[df["date"].apply(lambda d: is_date_in_season(d, start_month, end_month))]

	total_days = len(df)
	if total_days == 0:
		logger.warning("Condition summary: no days matched the requested window")
		return None

	df = df.copy()
	df["condition"] = df["code"].apply(weather_code_category)
	counts = df["condition"].value_counts()
	conditions = pd.DataFrame({
		"condition": counts.index,
		"days": counts.values,
	})
	conditions["share"] = conditions["days"] / total_days

	rainy = df["precip_sum"].fillna(0.0) >= RAIN_DAY_MM
	rainy_day_share = float(rainy.sum()) / total_days

	result = {
		"total_days": total_days,
		"conditions": conditions.reset_index(drop=True),
		"dominant": str(conditions.iloc[0]["condition"]),
		"rainy_day_share": rainy_day_share,
	}
	logger.debug("Condition summary: %d days, dominant=%s, rainy_share=%.2f",
	             total_days, result["dominant"], rainy_day_share)
	return result
