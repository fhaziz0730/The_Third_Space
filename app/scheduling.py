"""Find shared times, attach nearby venues, then assemble a small poll shortlist."""

import random
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from itertools import islice
from zoneinfo import ZoneInfo

from .activities import ACTIVITIES
from .models import AvailabilityWindow, Membership, Place
from .place_discovery import DiscoveredPlace, DiscoverySession
from .venues import rank_venues, venue_score


@dataclass
class Candidate:
    activity_tag: str
    starts_at: datetime
    available: list[Membership]
    place: Place | DiscoveredPlace | None = None

    @property
    def activity(self):
        return ACTIVITIES[self.activity_tag].label

    @property
    def duration_minutes(self):
        return ACTIVITIES[self.activity_tag].duration_minutes


def _utc_window_for_date(member: Membership, window: AvailabilityWindow, local_date: date):
    zone = ZoneInfo(member.timezone_name)
    start = datetime.combine(local_date, window.starts_at, zone).astimezone(timezone.utc)
    end_date = local_date + timedelta(days=1) if window.ends_at < window.starts_at else local_date
    end = datetime.combine(end_date, window.ends_at, zone).astimezone(timezone.utc)
    return start, end


def available_at(member, start, duration):
    local_day = start.astimezone(ZoneInfo(member.timezone_name)).date()
    for window in member.windows:
        if window.weekday != local_day.weekday():
            continue
        window_start, window_end = _utc_window_for_date(member, window, local_day)
        if window_start <= start and start + duration <= window_end:
            return True
    return False


def activity_tags(group):
    tags = {
        tag.strip().lower()
        for hobbies in [group.hobbies, *(m.hobbies for m in group.memberships)]
        for tag in hobbies.split(",")
        if tag.strip()
    }
    choices = [tag for tag in ACTIVITIES if tag in tags] if tags else list(ACTIVITIES)
    return choices or list(ACTIVITIES)[:3]


def shared_times(members, tags, now, horizon_days):
    """Yield unique majority-available time/activity combinations, without I/O."""
    seen = set()
    earliest = now + timedelta(days=1)
    majority = len(members) // 2 + 1
    for offset in range(1, horizon_days + 1):
        for tag in tags:
            duration = timedelta(minutes=ACTIVITIES[tag].duration_minutes)
            for member in members:
                local_day = (
                    (now + timedelta(days=offset)).astimezone(ZoneInfo(member.timezone_name)).date()
                )
                for window in member.windows:
                    if window.weekday != local_day.weekday():
                        continue
                    start, end = _utc_window_for_date(member, window, local_day)
                    start = max(start, earliest)
                    key = (tag, start)
                    if start + duration > end or key in seen:
                        continue
                    seen.add(key)
                    available = [m for m in members if available_at(m, start, duration)]
                    if len(available) >= majority:
                        yield Candidate(tag, start, available)


def venue_choices(db, slot, discovery):
    local = db.query(Place).filter_by(activity_tag=slot.activity_tag).all()
    external = discovery.search(slot.available, slot.activity_tag)
    ranked = rank_venues(local + external, slot.available)
    within_radius = [p for p in ranked if not venue_score(p, slot.available)[0]]
    return (within_radius or ranked)[:3]


def generate_candidates(db, group, horizon_days=30, limit=5, notices=None):
    if limit <= 0 or not group.memberships:
        return []
    tags = activity_tags(group)
    random.shuffle(tags)
    sampled = islice(
        shared_times(list(group.memberships), tags, datetime.now(timezone.utc), horizon_days),
        limit * 5,
    )
    slots = sorted(sampled, key=lambda slot: (-len(slot.available), slot.starts_at))[:limit]
    discovery = DiscoverySession()
    venues_by_attendees = {}
    alternatives = []
    for slot in slots:
        key = (slot.activity_tag, tuple(sorted(m.user_id for m in slot.available)))
        if key not in venues_by_attendees:
            venues_by_attendees[key] = venue_choices(db, slot, discovery)
        venues = venues_by_attendees[key] or [None]
        alternatives.append([replace(slot, place=place) for place in venues])

    # Reserve up to two slots for alternative venues without losing time variety.
    primary_count = max(1, limit - 2)
    options = [rows[0] for rows in alternatives[:primary_count]]
    extras = [option for rows in alternatives[:primary_count] for option in rows[1:]]
    options.extend(extras[: limit - len(options)])
    options.extend(rows[0] for rows in alternatives[primary_count:limit])
    if discovery.unavailable and notices is not None:
        notices.append("places-unavailable")
    return options[:limit]
