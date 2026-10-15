import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db import Base
from app.mock_data import DEMO_PASSWORD, seed_mock_data
from app.models import (
    RSVP,
    AvailabilityWindow,
    Group,
    Membership,
    Place,
    Poll,
    PollOption,
    User,
    Vote,
)
from app.security import password_matches


class MockDataTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_seed_has_working_accounts_and_poll_states_and_preserves_edits(self):
        self.assertTrue(seed_mock_data(self.db))
        for model, count in (
            (User, 6),
            (Group, 3),
            (Membership, 11),
            (AvailabilityWindow, 33),
            (Place, 4),
            (Poll, 3),
            (PollOption, 9),
            (Vote, 15),
            (RSVP, 3),
        ):
            self.assertEqual(self.db.query(model).count(), count, model.__name__)
        alex = self.db.query(User).filter_by(email="alex@example.com").one()
        self.assertTrue(password_matches(DEMO_PASSWORD, alex.password_hash))
        polls = self.db.query(Poll).order_by(Poll.id).all()
        self.assertIsNone(polls[0].closed_at)
        self.assertIsNotNone(polls[1].closed_at)
        self.assertIsNone(polls[1].confirmed_option_id)
        self.assertIn(polls[2].confirmed_option_id, [o.id for o in polls[2].options])
        self.assertEqual({r.response for r in self.db.query(RSVP)}, {"going", "maybe", "not going"})
        alex.display_name = "Edited demo user"
        self.db.commit()
        self.assertFalse(seed_mock_data(self.db))
        self.db.refresh(alex)
        self.assertEqual(alex.display_name, "Edited demo user")
        self.assertEqual(self.db.query(User).count(), 6)

    def test_existing_data_is_left_untouched(self):
        self.db.add(Place(name="Existing", activity_tag="coffee", latitude=0, longitude=0))
        self.db.commit()
        self.assertFalse(seed_mock_data(self.db))
        self.assertEqual(self.db.query(User).count(), 0)
        self.assertEqual(self.db.query(Place).one().name, "Existing")
