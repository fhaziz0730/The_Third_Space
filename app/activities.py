"""The activity catalog shared by profiles, scheduling, venues, and demo data."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Activity:
    label: str
    duration_minutes: int
    google_place_type: str


ACTIVITIES = {
    "walking": Activity("Neighborhood walk", 90, "park"),
    "hiking": Activity("Local hike", 120, "hiking_area"),
    "board games": Activity("Board game cafe", 120, "cafe"),
    "cooking": Activity("Cook together", 120, "restaurant"),
    "cycling": Activity("Casual bike ride", 120, "park"),
    "art": Activity("Art workshop", 120, "art_gallery"),
    "music": Activity("Live music", 120, "live_music_venue"),
    "coffee": Activity("Coffee meetup", 60, "cafe"),
    "reading": Activity("Bookshop visit", 90, "book_store"),
    "photography": Activity("Photo walk", 90, "park"),
}
