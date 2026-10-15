"""Profile form validation. Validate everything before changing a membership."""

from calendar import day_name
from datetime import datetime
from math import isfinite
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field

from .activities import ACTIVITIES
from .models import AvailabilityWindow, Membership
from .venues import KM_PER_MILE


def parse_schedule(schedule: str, timezone_name: str):
    try:
        ZoneInfo(timezone_name)
        windows = []
        for line in schedule.splitlines():
            if not line.strip():
                continue
            weekday, start, end = (part.strip() for part in line.split(","))
            weekday = int(weekday)
            start = datetime.strptime(start, "%H:%M").time()
            end = datetime.strptime(end, "%H:%M").time()
            if not 0 <= weekday <= 6 or start >= end:
                raise ValueError
            windows.append((weekday, start, end))
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError(
            "Use a valid time zone and one 'weekday,start,end' window per line, "
            "with the end later than the start on the same day. "
            "Weekdays are Monday=0 through Sunday=6."
        ) from exc
    ordered = sorted(windows)
    for previous, current in zip(ordered, ordered[1:]):
        if previous[0] == current[0] and current[1] < previous[2]:
            raise ValueError(
                f"Some availability windows overlap on {day_name[current[0]]}. "
                "Adjust the times before saving."
            )
    return windows


def parse_coordinates(latitude: str, longitude: str):
    try:
        lat = float(latitude) if latitude.strip() else None
        lon = float(longitude) if longitude.strip() else None
        if (lat is None) != (lon is None):
            raise ValueError
        if lat is not None and not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError
        return lat, lon
    except ValueError as exc:
        raise ValueError(
            "Choose a valid starting area, or clear the location and try again."
        ) from exc


class ProfileForm(BaseModel):
    timezone_name: str = "UTC"
    schedule: str = ""
    hobbies: list[str] = Field(default_factory=list)
    broad_location: str = ""
    exact_address: str = ""
    latitude: str = ""
    longitude: str = ""
    location_label: str = ""
    travel_radius_miles: str | None = None
    hide_hobbies: bool = False
    hide_availability: bool = False
    hide_location: bool = False
    allow_places_discovery: bool = False

    @classmethod
    def from_member(cls, member: Membership):
        return cls(
            timezone_name=member.timezone_name,
            schedule="\n".join(
                f"{w.weekday},{w.starts_at:%H:%M},{w.ends_at:%H:%M}" for w in member.windows
            ),
            hobbies=[tag.strip() for tag in member.hobbies.lower().split(",") if tag.strip()],
            broad_location=member.broad_location,
            exact_address=member.exact_address,
            latitude=str(member.latitude) if member.latitude is not None else "",
            longitude=str(member.longitude) if member.longitude is not None else "",
            location_label=member.broad_location if member.latitude is not None else "",
            travel_radius_miles=str(round(member.travel_radius_km / KM_PER_MILE, 2)),
            hide_hobbies=member.hide_hobbies,
            hide_availability=member.hide_availability,
            hide_location=member.hide_location,
            allow_places_discovery=member.allow_places_discovery,
        )

    def template_values(self, member: Membership):
        values = self.model_dump()
        values["hobbies"] = ",".join(self.hobbies)
        if self.travel_radius_miles is None:
            values["travel_radius_miles"] = str(member.travel_radius_km / KM_PER_MILE)
        return values

    def apply_to(self, member: Membership):
        # Parsing has no persistence side effects, including when later fields fail.
        lat, lon = parse_coordinates(self.latitude, self.longitude)
        if self.broad_location.strip() and (
            self.broad_location != self.location_label or lat is None
        ):
            raise ValueError(
                "Search and choose a matching location, or use your current location, before saving."
            )
        try:
            miles = float(self.template_values(member)["travel_radius_miles"])
            if not isfinite(miles) or not 0.1 <= miles <= 125:
                raise ValueError
        except ValueError as exc:
            raise ValueError("Choose a travel radius between 0.1 and 125 miles.") from exc
        hobbies = list(dict.fromkeys(self.hobbies))
        if len(hobbies) > 4 or any(hobby not in ACTIVITIES for hobby in hobbies):
            raise ValueError("Choose up to four hobbies from the available activities.")
        windows = parse_schedule(self.schedule, self.timezone_name)

        member.windows = [
            AvailabilityWindow(weekday=day, starts_at=start, ends_at=end)
            for day, start, end in windows
        ]
        member.timezone_name = self.timezone_name
        member.hobbies = ",".join(hobbies)
        member.broad_location = self.broad_location[:160]
        member.exact_address = self.exact_address[:400]
        member.latitude, member.longitude = lat, lon
        member.travel_radius_km = miles * KM_PER_MILE
        member.hide_hobbies = self.hide_hobbies
        member.hide_availability = self.hide_availability
        member.hide_location = self.hide_location
        member.allow_places_discovery = self.allow_places_discovery
