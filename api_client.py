import logging
import requests
from typing import Tuple, Dict, Any

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30

DAILY_VARIABLES = "temperature_2m_max,temperature_2m_min,precipitation_sum"

def get_coordinates(city_name: str) -> Tuple[float, float]:
	"""Returns latitude, longitude for a given city name using Open-Meteo Geocoding API."""
	url = "https://geocoding-api.open-meteo.com/v1/search"
	params = {"name": city_name, "count": 1, "format": "json"}
	logger.debug("Geocoding request: %s params=%s", url, params)
	try:
		response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
		response.raise_for_status()
	except requests.RequestException:
		logger.error("Geocoding request failed for city '%s'", city_name, exc_info=True)
		raise
	data = response.json()
	logger.debug("Geocoding response: %d result(s)", len(data.get("results", [])))

	if "results" not in data or len(data["results"]) == 0:
		logger.error("No coordinates found for city: %s", city_name)
		raise ValueError(f"Could not find coordinates for city: {city_name}")

	result = data["results"][0]
	logger.debug("Resolved '%s' to lat=%.4f, lon=%.4f", city_name, result["latitude"], result["longitude"])
	return result["latitude"], result["longitude"]

def fetch_historical_weather(
	lat: float, lon: float, start_date: str, end_date: str, *, with_weather_code: bool = True
) -> Dict[str, Any]:
	"""Fetches historical weather data from the Open-Meteo Archive API.

	Requests daily temperature, precipitation, and (by default) weather_code,
	which powers the plain-language condition summaries.
	"""
	url = "https://archive-api.open-meteo.com/v1/archive"
	daily = DAILY_VARIABLES + (",weather_code" if with_weather_code else "")
	params = {
		"latitude": lat,
		"longitude": lon,
		"start_date": start_date,
		"end_date": end_date,
		"daily": daily,
		"timezone": "auto",
	}
	logger.debug("Weather request: %s params=%s", url, params)
	try:
		response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
		response.raise_for_status()
	except requests.RequestException:
		logger.error("Weather request failed for lat=%.4f, lon=%.4f, %s to %s", lat, lon, start_date, end_date, exc_info=True)
		raise
	data = response.json()
	daily = data.get("daily", {})
	day_count = len(daily.get("time", []))
	weather_keys = [k for k in ("time", "temperature_2m_max", "temperature_2m_min", "precipitation_sum", "weather_code") if k in daily]
	logger.debug("Weather response: %d daily records, keys=%s", day_count, weather_keys)
	return data
