import requests
from typing import Tuple, Dict, Any

def get_coordinates(city_name: str) -> Tuple[float, float]:
    """Fetches latitude and longitude for a given city name using Open-Meteo Geocoding API."""
    url = f"https://geocoding-api.open-meteo.com/v1/search?name={city_name}&count=1&format=json"
    response = requests.get(url)
    response.raise_for_status()
    data = response.json()
    
    if "results" not in data or len(data["results"]) == 0:
        raise ValueError(f"Could not find coordinates for city: {city_name}")
        
    result = data["results"][0]
    return result["latitude"], result["longitude"]

def fetch_historical_weather(lat: float, lon: float, start_date: str, end_date: str) -> Dict[str, Any]:
    """Fetches historical weather data from Open-Meteo Archive API."""
    url = (
        f"https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={start_date}&end_date={end_date}"
        f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum"
        f"&timezone=auto"
    )
    response = requests.get(url)
    response.raise_for_status()
    return response.json()
