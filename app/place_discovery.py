"""Optional Google Places adapter. Only place IDs are saved by the application."""

from dataclasses import dataclass
import json
from math import atan2, cos, degrees, isfinite, radians, sin
import os
from urllib.error import URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

from .db import USE_MOCK_DATA
from .venues import distance_km, located_members

PLACE_TYPES = {
    "coffee": "cafe", "board games": "cafe", "reading": "book_store",
    "walking": "park", "photography": "park", "cycling": "park",
    "hiking": "hiking_area", "art": "art_gallery", "music": "live_music_venue",
    "cooking": "restaurant",
}
FIELDS = "id,displayName,formattedAddress,location,businessStatus,attributions"


def discovery_enabled():
    return (not USE_MOCK_DATA and os.getenv("PLACES_PROVIDER", "local").lower() == "google"
            and bool(os.getenv("GOOGLE_PLACES_API_KEY", "").strip()))


def maps_link(place_id):
    return "https://www.google.com/maps/search/?" + urlencode({
        "api": "1", "query": "venue", "query_place_id": place_id,
    })


@dataclass
class DiscoveredPlace:
    google_place_id: str
    name: str
    broad_location: str
    latitude: float
    longitude: float
    attributions: tuple = ()
    id: None = None

    @property
    def maps_url(self):
        return maps_link(self.google_place_id)


class PlacesUnavailable(Exception):
    pass


def _request(path, payload=None):
    headers = {"X-Goog-Api-Key": os.environ["GOOGLE_PLACES_API_KEY"],
               "X-Goog-FieldMask": ",".join(f"places.{f}" for f in FIELDS.split(",")) if payload else FIELDS,
               "Content-Type": "application/json"}
    request = Request("https://places.googleapis.com/v1/" + path, headers=headers,
                      data=json.dumps(payload).encode() if payload else None,
                      method="POST" if payload else "GET")
    try:
        with urlopen(request, timeout=4) as response:
            result = json.load(response)
        if not isinstance(result, dict) or "error" in result:
            raise PlacesUnavailable()
        return result
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        # Never surface upstream request details or API credentials to the user.
        raise PlacesUnavailable() from exc


def _parse_place(item):
    try:
        location = item["location"]
        lat, lon = float(location["latitude"]), float(location["longitude"])
        place_id, name = item["id"], item["displayName"]["text"]
        if (not isinstance(place_id, str) or not 1 <= len(place_id) <= 255
                or not isinstance(name, str) or not name.strip()
                or not isfinite(lat) or not isfinite(lon)
                or not -90 <= lat <= 90 or not -180 <= lon <= 180
                or item.get("businessStatus", "OPERATIONAL") != "OPERATIONAL"):
            return None
        attributions = []
        for attribution in item.get("attributions", []):
            uri = attribution.get("providerUri", "")
            attributions.append((attribution.get("provider", "Data provider"),
                                 uri if urlparse(uri).scheme == "https" else ""))
        return DiscoveredPlace(place_id, name, str(item.get("formattedAddress", "")), lat, lon,
                               tuple(attributions))
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def search_areas(members):
    """Rounded center and up to two outlying areas; handles the date line."""
    members = [m for m in located_members(members) if m.allow_places_discovery]
    if not members:
        return []
    lat = sum(m.latitude for m in members) / len(members)
    lon = degrees(atan2(sum(sin(radians(m.longitude)) for m in members),
                        sum(cos(radians(m.longitude)) for m in members)))
    radius = min(50, max(m.travel_radius_km or 25 for m in members))
    centers = [(round(lat, 2), round(lon, 2))]
    for member in sorted(members, key=lambda m: -distance_km(lat, lon, m.latitude, m.longitude)):
        point = (round(member.latitude, 2), round(member.longitude, 2))
        if all(distance_km(*point, *center) > radius for center in centers):
            centers.append(point)
        if len(centers) == 3:
            break
    return [(lat, lon, radius) for lat, lon in centers]


class DiscoverySession:
    """Request-scoped results and a hard cap of three searches per generation."""

    def __init__(self):
        self.remaining = 3
        self.cache = {}
        self.unavailable = False

    def search(self, members, tag):
        if not discovery_enabled() or self.unavailable or tag not in PLACE_TYPES:
            return []
        key = (tag, tuple(sorted(m.user_id for m in members)))
        if key in self.cache:
            return self.cache[key]
        places = {}
        for lat, lon, radius in search_areas(members):
            if self.remaining <= 0:
                break
            self.remaining -= 1
            try:
                result = _request("places:searchNearby", {
                    "includedTypes": [PLACE_TYPES[tag]], "maxResultCount": 10,
                    "rankPreference": "DISTANCE", "locationRestriction": {"circle": {
                        "center": {"latitude": lat, "longitude": lon}, "radius": radius * 1000}},
                })
                items = result.get("places", [])
                if not isinstance(items, list):
                    raise PlacesUnavailable()
                for item in items:
                    place = _parse_place(item)
                    if place:
                        places[place.google_place_id] = place
            except PlacesUnavailable:
                self.unavailable = True
                break
        self.cache[key] = list(places.values())
        return self.cache[key]


def get_place(place_id):
    if not discovery_enabled():
        return None
    try:
        return _parse_place(_request("places/" + quote(place_id, safe="")))
    except PlacesUnavailable:
        return None
