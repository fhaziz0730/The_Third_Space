"""Town/postal-code search; exact addresses are never read by this module."""

from functools import lru_cache
import json
from math import isfinite
import os
from time import monotonic
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from .db import USE_MOCK_DATA

SAMPLE_LOCATIONS = (
    ("Brooklyn, New York, United States", 40.6782, -73.9442, "11201"),
    ("Manhattan, New York, United States", 40.7831, -73.9712, "10001"),
    ("Queens, New York, United States", 40.7282, -73.7949, "11354"),
    ("New York City, New York, United States", 40.7128, -74.0060, "10007"),
    ("Jersey City, New Jersey, United States", 40.7178, -74.0431, "07302"),
    ("Boston, Massachusetts, United States", 42.3601, -71.0589, "02108"),
    ("Philadelphia, Pennsylvania, United States", 39.9526, -75.1652, "19106"),
)


class LocationSearchUnavailable(Exception):
    pass


def uses_sample_locations():
    return USE_MOCK_DATA or os.getenv("LOCATION_SEARCH_PROVIDER", "open-meteo") == "local"


@lru_cache(maxsize=256)
def _search_remote(query, time_bucket, customer_key):
    # Cache public locality results for up to ten minutes, never precise addresses.
    params = {"name": query, "count": 6, "language": "en", "format": "json"}
    host = "geocoding-api.open-meteo.com"
    if customer_key:
        host = "customer-geocoding-api.open-meteo.com"
        params["apikey"] = customer_key
    try:
        with urlopen(f"https://{host}/v1/search?{urlencode(params)}", timeout=4) as response:
            data = json.load(response)
        if not isinstance(data, dict) or data.get("error"):
            raise LocationSearchUnavailable()
        results = data.get("results", [])
        if not isinstance(results, list):
            raise LocationSearchUnavailable()
    except (URLError, OSError, TimeoutError, ValueError) as exc:
        raise LocationSearchUnavailable() from exc
    locations = []
    for result in results[:6]:
        try:
            lat, lon = float(result["latitude"]), float(result["longitude"])
            name = result["name"]
            if not isinstance(name, str) or not name or not isfinite(lat) or not isfinite(lon):
                continue
            if not -90 <= lat <= 90 or not -180 <= lon <= 180:
                continue
            label = ", ".join(dict.fromkeys(str(value) for value in
                              (name, result.get("admin1"), result.get("country")) if value))[:160]
            locations.append({"label": label, "latitude": round(lat, 4), "longitude": round(lon, 4)})
        except (KeyError, ValueError, TypeError):
            continue
    return tuple(locations)


def search_locations(query):
    query = " ".join(query.split())
    if not 2 <= len(query) <= 100:
        raise ValueError("Enter a town, city, or postal code between 2 and 100 characters.")
    if uses_sample_locations():
        return [{"label": label, "latitude": lat, "longitude": lon}
                for label, lat, lon, postal in SAMPLE_LOCATIONS
                if query.casefold() in label.casefold() or query == postal][:6]
    return list(_search_remote(query, int(monotonic() // 600),
                               os.getenv("OPEN_METEO_API_KEY", "").strip()))
