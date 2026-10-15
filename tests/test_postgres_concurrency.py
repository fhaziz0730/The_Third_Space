"""SQLite cannot verify row locks; exercise them on the disposable CI database."""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.migrate import upgrade_database
from app.models import Group, Membership, Poll, PollOption, User, Vote
from app.routes import groups, polls


@unittest.skipUnless(os.getenv("TEST_POSTGRES_URL"), "Requires disposable PostgreSQL")
class PostgresConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(os.environ["TEST_POSTGRES_URL"])
        with self.engine.begin() as connection:
            upgrade_database(connection)
        with Session(self.engine) as db:
            token = uuid4().hex
            users = [
                User(
                    email=f"{token}-{i}@example.com",
                    display_name=f"Concurrent {i}",
                    password_hash="unused",
                )
                for i in range(3)
            ]
            db.add_all(users)
            db.flush()
            self.user_ids = [u.id for u in users]
            group = Group(
                name="Concurrency fixture", owner_id=users[0].id, join_token=token, member_limit=2
            )
            db.add(group)
            db.flush()
            db.add(Membership(group_id=group.id, user_id=users[0].id, role="owner"))
            poll = Poll(
                group_id=group.id,
                created_by=users[0].id,
                closes_at=datetime.now(timezone.utc) + timedelta(hours=2),
            )
            db.add(poll)
            db.flush()
            option = PollOption(
                poll_id=poll.id,
                activity="Coffee meetup",
                duration_minutes=60,
                starts_at=datetime.now(timezone.utc) + timedelta(days=2),
            )
            db.add(option)
            db.flush()
            self.group_id, self.poll_id, self.option_id = group.id, poll.id, option.id
            self.join_token = token
            db.commit()

    def tearDown(self):
        self.engine.dispose()

    def request(self, user_id):
        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/",
                "query_string": b"",
                "headers": [],
                "session": {"user_id": user_id},
            }
        )

    def test_waiting_vote_refreshes_state_after_poll_closes(self):
        attempted_lock = Event()

        def observe(connection, cursor, statement, parameters, context, executemany):
            if "for update" in statement.lower() and "from polls" in statement.lower():
                attempted_lock.set()

        def vote_with_stale_identity_map():
            with Session(self.engine) as db:
                cached = db.get(Poll, self.poll_id)
                self.assertFalse(cached.is_closed)
                try:
                    polls.vote(self.request(self.user_ids[0]), self.option_id, db)
                except HTTPException as exc:
                    return exc.status_code
                return 303

        with Session(self.engine) as blocker:
            poll = blocker.query(Poll).filter_by(id=self.poll_id).with_for_update().one()
            poll.closed_at = datetime.now(timezone.utc)
            event.listen(self.engine, "before_cursor_execute", observe)
            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(vote_with_stale_identity_map)
            try:
                self.assertTrue(attempted_lock.wait(timeout=5))
                blocker.commit()
                self.assertEqual(future.result(timeout=5), 409)
            finally:
                blocker.rollback()
                executor.shutdown()
                event.remove(self.engine, "before_cursor_execute", observe)
        with Session(self.engine) as db:
            self.assertEqual(db.query(Vote).filter_by(option_id=self.option_id).count(), 0)

    def test_concurrent_joins_cannot_exceed_group_capacity(self):
        def join(user_id):
            with Session(self.engine) as db:
                return groups.join_group(self.request(user_id), self.join_token, db).status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(join, self.user_ids[1:]))
        self.assertEqual(sorted(results), [200, 303])
        with Session(self.engine) as db:
            self.assertEqual(db.query(Membership).filter_by(group_id=self.group_id).count(), 2)
