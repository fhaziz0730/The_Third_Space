from datetime import date, datetime, time, timedelta, timezone
import random
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from .models import AvailabilityWindow, Group, Membership, Place


ACTIVITIES = {
    "walking": ("Neighborhood walk", 90),
    "hiking": ("Local hike", 120),
    "board games": ("Board game cafe", 120),
    "cooking": ("Cook together", 120),
    "cycling": ("Casual bike ride", 120),
    "art": ("Art workshop", 120),
    "music": ("Live music", 120),
    "coffee": ("Coffee meetup", 60),
    "reading": ("Bookshop visit", 90),
    "photography": ("Photo walk", 90),
}


def _utc_window_for_date(member: Membership, window: AvailabilityWindow, local_date: date):
    zone = ZoneInfo(member.timezone_name)
    start = datetime.combine(local_date, window.starts_at, zone).astimezone(timezone.utc)
    end_date = local_date + timedelta(days=1) if window.ends_at <= window.starts_at else local_date
    end = datetime.combine(end_date, window.ends_at, zone).astimezone(timezone.utc)
    return start, end


def generate_candidates(db: Session, group: Group, horizon_days: int = 30, limit: int = 5):
    members = list(group.memberships)
    if not members:
        return []
    tags = set()
    tags.update(tag.strip().lower() for tag in group.hobbies.split(",") if tag.strip())
    for member in members:
        tags.update(tag.strip().lower() for tag in member.hobbies.split(",") if tag.strip())
    if not tags:
        tags.update(ACTIVITIES)
    activities = [value for tag, value in ACTIVITIES.items() if tag in tags]
    if not activities:
        activities = list(ACTIVITIES.values())[:3]
    random.shuffle(activities)

    now = datetime.now(timezone.utc)
    candidates = []
    for offset in range(1, horizon_days + 1):
        utc_day = (now + timedelta(days=offset)).date()
        for activity, duration_minutes in activities:
            # The initial prototype uses availability window starts as candidate starts.
            for member in members:
                local_day = (now + timedelta(days=offset)).astimezone(ZoneInfo(member.timezone_name)).date()
                for window in member.windows:
                    if window.weekday != local_day.weekday():
                        continue
                    start, end = _utc_window_for_date(member, window, local_day)
                    start = max(start, now + timedelta(days=1))
                    duration = timedelta(minutes=duration_minutes)
                    if end - start < duration:
                        continue
                    available = []
                    for other in members:
                        other_day = start.astimezone(ZoneInfo(other.timezone_name)).date()
                        fits = any(
                            w.weekday == other_day.weekday()
                            and (candidate_start := _utc_window_for_date(other, w, other_day))[0] <= start
                            and candidate_start[1] >= start + duration
                            for w in other.windows
                        )
                        if fits:
                            available.append(other)
                    if len(available) < max(1, (len(members) // 2) + 1):
                        continue
                    place = rank_places(db, members, activity)[0] if rank_places(db, members, activity) else None
                    candidates.append({
                        "activity": activity,
                        "duration_minutes": duration_minutes,
                        "starts_at": start,
                        "available": available,
                        "place": place,
                    })
                    if len(candidates) >= limit * 5:
                        break
                if len(candidates) >= limit * 5:
                    break
            if len(candidates) >= limit * 5:
                break
        if len(candidates) >= limit * 5:
            break
    # Keep times distinct while retaining interest and majority availability.
    unique = {}
    for candidate in candidates:
        key = (candidate["activity"], candidate["starts_at"])
        unique.setdefault(key, candidate)
    return sorted(unique.values(), key=lambda item: (-len(item["available"]), item["starts_at"]))[:limit]


def rank_places(db: Session, members: list[Membership], activity: str):
    tag = next((tag for tag, (label, _) in ACTIVITIES.items() if label == activity), activity.lower())
    places = db.query(Place).filter(Place.activity_tag == tag).all()
    located = [member for member in members if member.latitude is not None and member.longitude is not None]
    if not located:
        return []
    def distance_km(lat1, lon1, lat2, lon2):
        from math import asin, cos, radians, sin, sqrt
        dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
        a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
        return 6371 * 2 * asin(sqrt(a))
    return sorted(places, key=lambda place: (
        max(distance_km(m.latitude, m.longitude, place.latitude, place.longitude) for m in located)
        - min(distance_km(m.latitude, m.longitude, place.latitude, place.longitude) for m in located)
    ))
