from datetime import time
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import URLError

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.db import Base
from app.mock_data import seed_mock_data
from app.models import AvailabilityWindow, Group, Membership, Place, Poll, PollOption, User
from app.place_discovery import (DiscoveredPlace, DiscoverySession, PlacesUnavailable,
                                 _parse_place, _request, discovery_enabled, get_place, search_areas)
from app.routes import groups, polls
from app.scheduling import generate_candidates
from app.schema import upgrade_venue_preferences
from app.venues import distance_km, rank_venues, venue_summary


def member(lat=0, lon=0, radius=25, consent=False, user_id=1):
    return SimpleNamespace(latitude=lat, longitude=lon, travel_radius_km=radius,
                           allow_places_discovery=consent, user_id=user_id)


def place(name, lat, lon):
    return SimpleNamespace(name=name, latitude=lat, longitude=lon)


class VenueRankingTests(unittest.TestCase):
    def test_nearby_beats_equally_distant_far_venue(self):
        members = [member(lon=-.01), member(lon=.01)]
        near, far = place("Near", 0, .01), place("Far", 10, 0)
        self.assertEqual(rank_venues([far, near], members), [near, far])

    def test_respects_individual_radius_before_minimizing_longest_journey(self):
        members = [member(lon=0, radius=2), member(lon=.1, radius=20)]
        fair, within = place("Midpoint", 0, .05), place("Within both", 0, .01)
        self.assertEqual(rank_venues([fair, within], members), [within, fair])

    def test_minimizes_longest_journey_then_average(self):
        members = [member(lon=0, radius=200), member(lon=.1, radius=200)]
        center, edge = place("Center", 0, .05), place("Edge", 0, 0)
        self.assertEqual(rank_venues([edge, center], members)[0], center)

    def test_missing_coordinates_and_private_summary(self):
        viewer, missing = member(), member(lat=None, lon=None)
        venue = place("Cafe", 0, .01)
        self.assertEqual(rank_venues([venue], [missing]), [])
        summary = venue_summary(venue, [viewer, missing], viewer)
        self.assertEqual(summary["missing"], 1)
        self.assertAlmostEqual(summary["my_distance"], 1.112, places=2)
        self.assertTrue(summary["within_radius"])
        self.assertNotIn("distances", summary)
        self.assertEqual(distance_km(0, 0, 0, 0), 0)


class DiscoveryTests(unittest.TestCase):
    def test_mock_mode_disables_network_even_with_credentials(self):
        with patch.dict(os.environ, {"PLACES_PROVIDER": "google", "GOOGLE_PLACES_API_KEY": "secret"}), \
                patch("app.place_discovery.USE_MOCK_DATA", True), \
                patch("app.place_discovery.urlopen") as network:
            self.assertFalse(discovery_enabled())
            self.assertEqual(DiscoverySession().search([member(consent=True)], "coffee"), [])
            self.assertIsNone(get_place("test"))
            network.assert_not_called()

    def test_no_opt_in_means_no_search(self):
        with patch("app.place_discovery.discovery_enabled", return_value=True), \
                patch("app.place_discovery._request") as api:
            self.assertEqual(DiscoverySession().search([member()], "coffee"), [])
            api.assert_not_called()

    def test_rounded_search_areas_exclude_unconsenting_users(self):
        areas = search_areas([member(40.67891, -73.98765, consent=True),
                              member(-30, 100, consent=False)])
        self.assertEqual(areas, [(40.68, -73.99, 25)])
        date_line = search_areas([member(0, 179, consent=True), member(0, -179, consent=True)])
        self.assertEqual(abs(date_line[0][1]), 180)

    def test_search_budget_deduplication_and_request_scoped_cache(self):
        result = {"places": [{"id": "venue-id", "displayName": {"text": "Cafe"},
                              "location": {"latitude": 0, "longitude": 0}}]}
        members = [member(lon=lon, consent=True, user_id=i) for i, lon in enumerate((0, 10, 20))]
        with patch("app.place_discovery.discovery_enabled", return_value=True), \
                patch("app.place_discovery._request", return_value=result) as api:
            session = DiscoverySession()
            self.assertEqual(len(session.search(members, "coffee")), 1)
            session.search(members, "coffee")
            session.search(members, "reading")
            self.assertEqual(api.call_count, 3)
            self.assertEqual(session.remaining, 0)

    def test_upstream_failure_falls_back_and_stops_further_requests(self):
        with patch("app.place_discovery.discovery_enabled", return_value=True), \
                patch("app.place_discovery._request", side_effect=PlacesUnavailable) as api:
            session = DiscoverySession()
            self.assertEqual(session.search([member(consent=True)], "coffee"), [])
            self.assertTrue(session.unavailable)
            session.search([member(consent=True)], "reading")
            api.assert_called_once()

    def test_http_contract_and_timeout(self):
        with patch.dict(os.environ, {"GOOGLE_PLACES_API_KEY": "test-key"}), \
                patch("app.place_discovery.urlopen") as network:
            network.return_value.__enter__.return_value.read.return_value = b'{"places": []}'
            payload = {"includedTypes": ["cafe"]}
            self.assertEqual(_request("places:searchNearby", payload), {"places": []})
            request = network.call_args.args[0]
            self.assertEqual(request.method, "POST")
            self.assertEqual(json.loads(request.data), payload)
            self.assertEqual(network.call_args.kwargs["timeout"], 4)
            self.assertIn("places.attributions", request.get_header("X-goog-fieldmask"))
            network.side_effect = URLError("private upstream details")
            with self.assertRaises(PlacesUnavailable):
                _request("places:searchNearby", payload)

    def test_invalid_or_closed_results_are_ignored(self):
        base = {"id": "venue", "displayName": {"text": "Cafe"},
                "location": {"latitude": 0, "longitude": 0}}
        self.assertIsNotNone(_parse_place(base))
        for bad in ({}, None, {**base, "businessStatus": "CLOSED_PERMANENTLY"},
                    {**base, "location": {"latitude": float("nan"), "longitude": 0}}):
            self.assertIsNone(_parse_place(bad))


class VenueIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        seed_mock_data(self.db)
        self.group = self.db.query(Group).filter_by(name="Brooklyn Coffee & Games").one()
        self.user = self.db.get(User, self.group.owner_id)
        for membership in self.group.memberships:
            membership.hobbies = "coffee"
            membership.windows = [AvailabilityWindow(weekday=day, starts_at=time(0), ends_at=time(23, 59))
                                  for day in range(7)]
        self.group.hobbies = "coffee"
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def request(self):
        return Request({"type": "http", "method": "GET", "path": "/", "query_string": b"",
                        "headers": [], "session": {"user_id": self.user.id}})

    def save(self, **kwargs):
        fields = dict(timezone_name="UTC", schedule="0,09:00,10:00", hobbies=["coffee"],
                      broad_location="Brooklyn", exact_address="", latitude="40.68", longitude="-73.98",
                      hide_hobbies=None, hide_availability=None, hide_location=None, db=self.db)
        fields.update(kwargs)
        return groups.save_availability(self.request(), self.group.id, **fields)

    def test_radius_and_discovery_preferences_save_and_validation_preserves_data(self):
        self.assertEqual(self.save(travel_radius_miles="12.5", allow_places_discovery="on").status_code, 303)
        membership = next(m for m in self.group.memberships if m.user_id == self.user.id)
        self.assertEqual(membership.travel_radius_km, 12.5 * 1.609344)
        self.assertTrue(membership.allow_places_discovery)
        for radius in ("nan", "inf", "0", "201", "invalid"):
            response = self.save(travel_radius_miles=radius)
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"between 0.1 and 125", response.body)
            self.assertEqual(membership.travel_radius_km, 12.5 * 1.609344)
            self.assertTrue(membership.allow_places_discovery)

    def test_existing_radius_displays_in_miles_and_omitted_field_preserves_it(self):
        membership = next(m for m in self.group.memberships if m.user_id == self.user.id)
        membership.travel_radius_km = 16.09344
        self.db.commit()
        response = groups.availability_page(self.request(), self.group.id, self.db)
        self.assertIn(b'Preferred travel radius (miles)', response.body)
        self.assertIn(b'name="travel_radius_miles"', response.body)
        self.assertIn(b'value="10.0"', response.body)
        self.assertEqual(self.save().status_code, 303)
        self.assertAlmostEqual(membership.travel_radius_km, 16.09344)

    def test_poll_displays_distance_in_miles(self):
        response = groups.create_suggestions(self.request(), self.group.id, self.db)
        poll_id = int(response.headers["location"].split("/")[-1])
        page = polls.poll_page(self.request(), self.group.id, poll_id, self.db)
        self.assertIn(b"miles from your starting area", page.body)
        self.assertNotIn(b"km from your starting area", page.body)

    def test_only_available_members_influence_venue_ranking_and_multiple_choices(self):
        unavailable = self.group.memberships[0]
        unavailable.windows.clear()
        unavailable.latitude, unavailable.longitude = -30, 100
        self.db.add(Place(name="Second nearby cafe", activity_tag="coffee", latitude=40.68, longitude=-73.98))
        self.db.add(Place(name="Faraway cafe", activity_tag="coffee", latitude=0, longitude=20))
        self.db.commit()
        with patch("app.place_discovery.discovery_enabled", return_value=False):
            options = generate_candidates(self.db, self.group, horizon_days=7)
        self.assertTrue(options)
        self.assertLessEqual(len(options), 5)
        self.assertTrue(all(unavailable not in o["available"] for o in options))
        self.assertGreaterEqual(len({o["place"].name for o in options}), 2)
        self.assertTrue(all(o["place"].name != "Faraway cafe" for o in options))

    def test_google_poll_persists_only_id_and_renders_live_details_with_fallback(self):
        external = DiscoveredPlace("external-id", "External cafe", "Test area", 40.68, -73.98)
        place_count = self.db.query(Place).count()
        with patch("app.place_discovery.DiscoverySession.search", return_value=[external]):
            response = groups.create_suggestions(self.request(), self.group.id, self.db)
        poll_id = int(response.headers["location"].split("/")[-1])
        poll = self.db.get(Poll, poll_id)
        self.assertTrue(any(o.google_place_id == "external-id" for o in poll.options))
        self.assertEqual(self.db.query(Place).count(), place_count)
        with patch("app.routes.polls.get_place", return_value=external) as fetch:
            page = polls.poll_page(self.request(), self.group.id, poll_id, self.db)
        self.assertIn(b"External cafe", page.body)
        self.assertIn(b"Google Maps", page.body)
        self.assertEqual(page.headers["Cache-Control"], "no-store")
        fetch.assert_called_once_with("external-id")
        with patch("app.routes.polls.get_place", return_value=None):
            page = polls.poll_page(self.request(), self.group.id, poll_id, self.db)
        self.assertIn(b"Venue details are unavailable", page.body)

    def test_schema_upgrade_preserves_existing_records_and_is_repeatable(self):
        old = create_engine("sqlite:///:memory:")
        try:
            with old.begin() as connection:
                connection.execute(text("CREATE TABLE memberships (id INTEGER PRIMARY KEY)"))
                connection.execute(text("CREATE TABLE poll_options (id INTEGER PRIMARY KEY)"))
                connection.execute(text("INSERT INTO memberships (id) VALUES (123)"))
            upgrade_venue_preferences(old)
            upgrade_venue_preferences(old)
            with old.connect() as connection:
                row = connection.execute(text("SELECT id, travel_radius_km, allow_places_discovery FROM memberships")).one()
                self.assertEqual(tuple(row), (123, 25, 0))
            self.assertIn("google_place_id", {c["name"] for c in inspect(old).get_columns("poll_options")})
        finally:
            old.dispose()
