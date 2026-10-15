"""Local distance ranking; no user coordinates are exposed in venue summaries."""

from math import asin, cos, isfinite, radians, sin, sqrt


def located_members(members):
    return [member for member in members
            if member.latitude is not None and member.longitude is not None
            and isfinite(member.latitude) and isfinite(member.longitude)
            and -90 <= member.latitude <= 90 and -180 <= member.longitude <= 180]


def distance_km(lat1, lon1, lat2, lon2):
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 6371 * 2 * asin(sqrt(max(0, min(1, a))))


def venue_score(place, members):
    located = located_members(members)
    distances = [distance_km(m.latitude, m.longitude, place.latitude, place.longitude) for m in located]
    outside = sum(distance > (member.travel_radius_km or 25)
                  for member, distance in zip(located, distances))
    # Favor everyone's preferred radius, then the worst journey, then the average.
    return (outside > 0, max(distances, default=float("inf")),
            sum(distances) / len(distances) if distances else float("inf"))


def rank_venues(places, members):
    if not located_members(members):
        return []
    return sorted(places, key=lambda place: (*venue_score(place, members), place.name))


def venue_summary(place, members, viewer):
    located = located_members(members)
    if not located:
        return {"located": 0, "missing": len(members), "within_radius": False, "my_distance": None}
    my_distance = (distance_km(viewer.latitude, viewer.longitude, place.latitude, place.longitude)
                   if viewer in located else None)
    return {"located": len(located), "missing": len(members) - len(located),
            "within_radius": not venue_score(place, located)[0], "my_distance": my_distance}
