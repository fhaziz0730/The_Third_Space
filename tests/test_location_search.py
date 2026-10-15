import asyncio
import json
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.db import Base, get_db
from app.location_search import LocationSearchUnavailable, _search_remote, search_locations
from app.mock_data import seed_mock_data
from app.models import Group, User
from app.profiles import ProfileForm
from app.routes import profiles


class LocationSearchTests(unittest.TestCase):
    def tearDown(self):
        _search_remote.cache_clear()

    def test_mock_search_works_by_name_or_postal_code_without_network(self):
        with (
            patch("app.location_search.is_mock_mode", return_value=True),
            patch("app.location_search.urlopen") as network,
        ):
            self.assertEqual(
                search_locations("11201")[0]["label"], "Brooklyn, New York, United States"
            )
            self.assertEqual(search_locations("brooklyn")[0]["latitude"], 40.6782)
            self.assertEqual(search_locations("Not a sample city"), [])
            network.assert_not_called()

    def test_remote_search_formats_choices_filters_invalid_results_and_caches(self):
        result = {
            "results": [
                {
                    "name": "Cambridge",
                    "admin1": "Massachusetts",
                    "country": "United States",
                    "latitude": 42.375099,
                    "longitude": -71.105616,
                },
                {"name": "Invalid", "latitude": 1000, "longitude": 0},
                {"name": "Invalid", "latitude": float("nan"), "longitude": 0},
            ]
        }
        with patch("app.location_search.urlopen") as network:
            network.return_value.__enter__.return_value.read.return_value = json.dumps(
                result
            ).encode()
            locations = _search_remote("Cambridge", 1, "")
            self.assertEqual(len(locations), 1)
            self.assertEqual(locations[0]["label"], "Cambridge, Massachusetts, United States")
            self.assertEqual(locations[0]["latitude"], 42.3751)
            self.assertEqual(_search_remote("Cambridge", 1, ""), locations)
            network.assert_called_once()
            self.assertEqual(network.call_args.kwargs["timeout"], 4)

    def test_search_validation_and_service_errors(self):
        for query in ("", "a", "x" * 101):
            with self.assertRaises(ValueError):
                search_locations(query)
        with patch("app.location_search.urlopen", side_effect=TimeoutError):
            with self.assertRaises(LocationSearchUnavailable):
                _search_remote("Boston", 1, "")


class LocationProfileTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        seed_mock_data(self.db)
        self.group = self.db.query(Group).first()
        self.user = self.db.get(User, self.group.owner_id)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def request(self, user=None):
        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/",
                "query_string": b"",
                "headers": [],
                "session": {"user_id": user.id} if user else {},
            }
        )

    def save(self, **overrides):
        fields = dict(
            timezone_name="UTC",
            schedule="",
            hobbies=["coffee"],
            broad_location="Boston",
            exact_address="",
            latitude="42.36",
            longitude="-71.06",
            hide_hobbies=None,
            hide_availability=None,
            hide_location=None,
            db=self.db,
            location_label="Boston",
        )
        fields.update(overrides)
        fields.pop("db")
        for key in ("hide_hobbies", "hide_availability", "hide_location"):
            fields[key] = bool(fields.get(key))
        return profiles.save_availability(
            self.request(self.user), self.group.id, ProfileForm(**fields), self.db
        )

    def test_search_requires_membership_and_does_not_save_location(self):
        membership = next(m for m in self.group.memberships if m.user_id == self.user.id)
        previous = (membership.broad_location, membership.latitude, membership.longitude)
        with patch(
            "app.routes.profiles.search_locations", return_value=[{"label": "Boston"}]
        ) as search:
            with self.assertRaises(HTTPException):
                profiles.location_search(self.request(), self.group.id, "Boston", self.db)
            search.assert_not_called()
            response = profiles.location_search(
                self.request(self.user), self.group.id, "Boston", self.db
            )
            self.assertEqual(response.status_code, 200)
        self.assertEqual(
            (membership.broad_location, membership.latitude, membership.longitude), previous
        )

    def test_backend_errors_are_useful(self):
        with patch("app.routes.profiles.search_locations", side_effect=LocationSearchUnavailable):
            self.assertEqual(
                profiles.location_search(
                    self.request(self.user), self.group.id, "Boston", self.db
                ).status_code,
                503,
            )
        with patch("app.routes.profiles.search_locations", side_effect=ValueError("Enter a town")):
            self.assertEqual(
                profiles.location_search(
                    self.request(self.user), self.group.id, "a", self.db
                ).status_code,
                400,
            )

    def test_selection_saved_and_clear_removes_coordinates(self):
        self.assertEqual(self.save().status_code, 303)
        membership = next(m for m in self.group.memberships if m.user_id == self.user.id)
        self.assertEqual(membership.broad_location, "Boston")
        self.assertEqual(membership.latitude, 42.36)
        self.assertEqual(
            self.save(broad_location="", location_label="", latitude="", longitude="").status_code,
            303,
        )
        self.assertIsNone(membership.latitude)
        self.assertIsNone(membership.longitude)

    def test_unselected_text_cannot_silently_reuse_old_coordinates(self):
        membership = next(m for m in self.group.memberships if m.user_id == self.user.id)
        previous = (membership.broad_location, membership.latitude, membership.longitude)
        response = self.save(broad_location="New town", location_label="Boston")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"choose a matching location", response.body)
        self.assertEqual(response.context["form_values"]["location_label"], "Boston")
        self.assertEqual(
            (membership.broad_location, membership.latitude, membership.longitude), previous
        )

    def test_profile_hides_coordinate_fields(self):
        response = profiles.availability_page(self.request(self.user), self.group.id, self.db)
        self.assertIn(b"Town or postal code", response.body)
        self.assertRegex(response.body, rb'<input\s+type="hidden"\s+name="latitude"')
        self.assertNotIn(b"Approximate latitude", response.body)

    def test_browser_form_with_empty_selection_is_rejected(self):
        app = FastAPI()
        app.include_router(profiles.router)
        app.dependency_overrides[get_db] = lambda: self.db
        body = urlencode(
            {
                "broad_location": "Boston",
                "location_label": "",
                "location_picker": "true",
                "latitude": "",
                "longitude": "",
                "hobbies": "coffee",
            }
        ).encode()
        scope = {
            "type": "http",
            "method": "POST",
            "path": f"/groups/{self.group.id}/availability",
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
            "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
            "session": {"user_id": self.user.id},
        }
        messages = []
        received = False

        async def receive():
            nonlocal received
            if received:
                return {"type": "http.disconnect"}
            received = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            messages.append(message)

        asyncio.run(app(scope, receive, send))
        self.assertEqual(messages[0]["status"], 200)
        self.assertIn(b"choose a matching location", messages[1]["body"])
