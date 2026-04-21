import logging
import requests
from typing import Tuple, Dict, Any

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30

def get_coordinates(city_name: str) -> Tuple[float, float]:
    """Fetches latitude and longitude for a given city name using Open-Meteo Geocoding API."""
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

def fetch_historical_weather(lat: float, lon: float, start_date: str, end_date: str) -> Dict[str, Any]:
    """Fetches historical weather data from Open-Meteo Archive API."""
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
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
    day_count = len(data.get("daily", {}).get("time", []))
    logger.debug("Weather response: %d daily records", day_count)
    return data
