import unittest
from datetime import datetime, time, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.db import Base
from app.models import AvailabilityWindow, Group, Membership, Place, Poll, PollOption, RSVP, User, Vote
from app.routes import auth, groups, places, polls
from app.security import hash_password
from app.web import templates


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        self.users = [User(email=f"person{i}@example.com", display_name=f"Person {i}", password_hash=hash_password("test-password")) for i in range(3)]
        self.db.add_all(self.users)
        self.db.flush()
        self.group = Group(name="Test group", owner_id=self.users[0].id, join_token="test-invitation")
        self.db.add(self.group)
        self.db.flush()
        self.members = [Membership(group_id=self.group.id, user_id=user.id, role=role) for user, role in zip(self.users, ["owner", "admin", "member"])]
        self.db.add_all(self.members)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def request(self, user=None, session=None):
        if session is None:
            session = {"user_id": user.id} if user else {}
        return Request({"type": "http", "method": "GET", "path": "/", "query_string": b"", "headers": [], "session": session})

    def make_poll(self, counts=(2, 2, 0), closed=True, expired=False):
        now = datetime.now(timezone.utc)
        poll = Poll(group_id=self.group.id, created_by=self.users[0].id, closes_at=now + timedelta(hours=-1 if expired else 2), closed_at=now if closed else None)
        self.db.add(poll)
        self.db.flush()
        for index, count in enumerate(counts):
            option = PollOption(activity="Coffee meetup", duration_minutes=60, starts_at=now + timedelta(days=index + 1), available_user_ids=",".join(str(user.id) for user in self.users))
            poll.options.append(option)
            self.db.flush()
            self.db.add_all(Vote(option_id=option.id, user_id=user.id) for user in self.users[:count])
        self.db.commit()
        return poll

    def assert_http_error(self, status, function, *args, **kwargs):
        with self.assertRaises(HTTPException) as raised:
            function(*args, **kwargs)
        self.assertEqual(raised.exception.status_code, status)

    def test_places_catalog_and_add(self):
        request = self.request(self.users[0])
        self.assertEqual(places.place_catalog_page(request, self.db).status_code, 200)
        response = places.add_place(request, name="Test cafe", activity_tag="coffee", broad_location="Town", latitude=40, longitude=-74, description="", db=self.db)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.db.query(Place).count(), 1)
        self.assertIn(b"Test cafe", places.place_catalog_page(request, self.db).body)
        self.assertEqual(places.place_catalog_page(self.request(), self.db).headers["location"], "/login")

    def test_partial_tie_only_shows_winners_to_organizer(self):
        poll = self.make_poll()
        response = polls.poll_page(self.request(self.users[0]), self.group.id, poll.id, self.db)
        self.assertTrue(response.context["tied"])
        self.assertEqual(response.context["winning_option_ids"], [option.id for option in poll.options[:2]])
        self.assertEqual(response.body.count(b"Confirm this option"), 2)
        response = polls.poll_page(self.request(self.users[1]), self.group.id, poll.id, self.db)
        self.assertNotIn(b"Confirm this option", response.body)

    def test_tied_loser_and_admin_cannot_confirm(self):
        poll = self.make_poll()
        self.assert_http_error(400, polls.confirm_poll, self.request(self.users[0]), poll.id, option_id=poll.options[2].id, db=self.db)
        self.assert_http_error(403, polls.confirm_poll, self.request(self.users[1]), poll.id, option_id=poll.options[0].id, db=self.db)
        self.assertIsNone(poll.confirmed_option_id)
        response = polls.confirm_poll(self.request(self.users[0]), poll.id, option_id=poll.options[1].id, db=self.db)
        self.assertEqual(response.status_code, 303)

    def test_confirmation_cannot_change_existing_rsvps(self):
        poll = self.make_poll()
        polls.confirm_poll(self.request(self.users[0]), poll.id, option_id=poll.options[0].id, db=self.db)
        polls.rsvp(self.request(self.users[2]), poll.options[0].id, response="going", db=self.db)
        self.assert_http_error(409, polls.confirm_poll, self.request(self.users[0]), poll.id, option_id=poll.options[1].id, db=self.db)
        self.assertEqual(poll.confirmed_option_id, poll.options[0].id)
        self.assertEqual(self.db.query(RSVP).one().option_id, poll.options[0].id)

    def test_unique_winner_can_be_confirmed_by_admin(self):
        poll = self.make_poll(counts=(2, 1, 0))
        self.assert_http_error(400, polls.confirm_poll, self.request(self.users[1]), poll.id, option_id=poll.options[1].id, db=self.db)
        response = polls.confirm_poll(self.request(self.users[1]), poll.id, option_id=poll.options[0].id, db=self.db)
        self.assertEqual(response.status_code, 303)

    def test_expired_poll_can_be_confirmed_without_visiting_page(self):
        poll = self.make_poll(counts=(2, 1), closed=False, expired=True)
        self.db.expire_all()
        response = polls.confirm_poll(self.request(self.users[1]), poll.id, option_id=poll.options[0].id, db=self.db)
        self.assertEqual(response.status_code, 303)
        self.assertIsNotNone(poll.closed_at)

    def test_open_poll_cannot_be_confirmed(self):
        poll = self.make_poll(counts=(2, 1), closed=False)
        self.assert_http_error(409, polls.confirm_poll, self.request(self.users[0]), poll.id, option_id=poll.options[0].id, db=self.db)

    def test_all_zero_votes_are_an_organizer_tie(self):
        poll = self.make_poll(counts=(0, 0, 0))
        self.assert_http_error(403, polls.confirm_poll, self.request(self.users[1]), poll.id, option_id=poll.options[0].id, db=self.db)
        self.assertEqual(polls.confirm_poll(self.request(self.users[0]), poll.id, option_id=poll.options[2].id, db=self.db).status_code, 303)

    def test_vote_close_confirm_rsvp_flow(self):
        poll = self.make_poll(counts=(0, 0), closed=False)
        request = self.request(self.users[2])
        self.assertEqual(polls.vote(request, poll.options[0].id, self.db).status_code, 303)
        self.assertEqual(polls.unvote(request, poll.options[0].id, self.db).status_code, 303)
        polls.vote(request, poll.options[1].id, self.db)
        polls.close_poll(self.request(self.users[0]), poll.id, self.db)
        self.assert_http_error(409, polls.vote, request, poll.options[0].id, self.db)
        polls.confirm_poll(self.request(self.users[1]), poll.id, option_id=poll.options[1].id, db=self.db)
        polls.rsvp(request, poll.options[1].id, response="going", db=self.db)
        self.assertEqual(self.db.query(RSVP).one().response, "going")

    def test_invitation_survives_failed_login_and_registration_navigation(self):
        request = self.request()
        groups.join_page(request, self.group.join_token, self.db)
        self.assertEqual(request.session["pending_invitation"], "/join/test-invitation")
        auth.login_page(request)
        auth.register_page(request)
        self.assertIn(b"incorrect", auth.login(request, email=self.users[0].email, password="wrong", db=self.db).body)
        response = auth.login(request, email=self.users[0].email, password="test-password", db=self.db)
        self.assertEqual(response.headers["location"], "/join/test-invitation")
        self.assertNotIn("pending_invitation", request.session)

    def test_invitation_registration_and_join(self):
        request = self.request()
        self.assertEqual(groups.join_group(request, self.group.join_token, self.db).headers["location"], "/login")
        response = auth.register(request, email="new@example.com", display_name="New", password="test-password", db=self.db)
        self.assertEqual(response.headers["location"], "/join/test-invitation")
        response = groups.join_group(request, self.group.join_token, self.db)
        self.assertEqual(response.headers["location"], f"/groups/{self.group.id}/availability")

    def test_sign_in_rejects_external_redirects(self):
        for destination in ["https://example.com", "//example.com", "/join/../logout", None]:
            with self.subTest(destination=destination):
                request = self.request(session={"pending_invitation": destination})
                response = auth.complete_sign_in(request, self.users[0])
                self.assertEqual(response.headers["location"], "/")

    def test_invalid_availability_preserves_existing_windows(self):
        member = self.members[0]
        member.windows.append(AvailabilityWindow(weekday=0, starts_at=time(9), ends_at=time(10)))
        self.db.commit()
        for schedule in ["0,09:00,09:00", "0,10:00,09:00", "0,09:00,11:00\n0,10:00,12:00"]:
            with self.subTest(schedule=schedule):
                response = self.save_schedule(schedule)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'class="error"', response.body)
                self.assertEqual(response.context["form_values"]["schedule"], schedule)
                self.assertEqual([(w.starts_at, w.ends_at) for w in member.windows], [(time(9), time(10))])
        self.assertEqual(self.save_schedule("0,09:00,10:00\n0,10:00,11:00").status_code, 303)
        self.assertEqual(len(member.windows), 2)

    def save_schedule(self, schedule):
        return groups.save_availability(self.request(self.users[0]), self.group.id, timezone_name="UTC", schedule=schedule, hobbies=["coffee"], broad_location="", exact_address="", latitude="", longitude="", hide_hobbies=None, hide_availability=None, hide_location=None, db=self.db)

    def test_templates_compile(self):
        for name in templates.env.list_templates():
            with self.subTest(template=name):
                templates.env.get_template(name)


if __name__ == "__main__":
    unittest.main()
