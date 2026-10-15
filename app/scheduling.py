from datetime import date, datetime, time, timedelta, timezone
import random
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from .models import AvailabilityWindow, Group, Membership, Place
from .place_discovery import DiscoverySession
from .venues import rank_venues, venue_score


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
    end_date = local_date + timedelta(days=1) if window.ends_at < window.starts_at else local_date
    end = datetime.combine(end_date, window.ends_at, zone).astimezone(timezone.utc)
    return start, end


def generate_candidates(db: Session, group: Group, horizon_days: int = 30, limit: int = 5, notices=None):
    if limit <= 0:
        return []
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
                    candidates.append({
                        "activity": activity,
                        "duration_minutes": duration_minutes,
                        "starts_at": start,
                        "available": available,
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
    slots = sorted(unique.values(), key=lambda item: (-len(item["available"]), item["starts_at"]))[:limit]
    discovery = DiscoverySession()
    ranked_cache = {}
    alternatives = []
    for slot in slots:
        tag = next(tag for tag, (label, _) in ACTIVITIES.items() if label == slot["activity"])
        key = (tag, tuple(sorted(m.user_id for m in slot["available"])))
        if key not in ranked_cache:
            local = db.query(Place).filter(Place.activity_tag == tag).all()
            external = discovery.search(slot["available"], tag)
            ranked = rank_venues(local + external, slot["available"])
            within_radius = [place for place in ranked if not venue_score(place, slot["available"])[0]]
            ranked_cache[key] = (within_radius or ranked)[:3]
        alternatives.append([{**slot, "place": place} for place in ranked_cache[key]]
                            or [{**slot, "place": None}])
    # Keep time/activity variety before filling spare poll slots with venue choices.
    primary_count = max(1, limit - 2)
    options = [rows[0] for rows in alternatives[:primary_count]]
    extras = [row for rows in alternatives[:primary_count] for row in rows[1:]]
    options.extend(extras[:max(0, limit - len(options))])
    options.extend(rows[0] for rows in alternatives[primary_count:limit])
    if discovery.unavailable and notices is not None:
        notices.append("places-unavailable")
    return options[:limit]


def rank_places(db: Session, members: list[Membership], activity: str):
    tag = next((tag for tag, (label, _) in ACTIVITIES.items() if label == activity), activity.lower())
    places = db.query(Place).filter(Place.activity_tag == tag).all()
    return rank_venues(places, members)
