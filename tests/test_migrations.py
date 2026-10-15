import os
import unittest

from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.db import Base
from app.migrate import upgrade_database
from app.models import User
from app.security import hash_password


class MigrationTests(unittest.TestCase):
    def test_fresh_database_and_repeat_upgrade(self):
        engine = create_engine("sqlite://")
        try:
            with engine.begin() as connection:
                upgrade_database(connection)
                upgrade_database(connection)
                self.assertEqual(MigrationContext.configure(connection).get_current_revision(), "0003_auth_limits")
                self.assertEqual(set(inspect(connection).get_table_names()), set(Base.metadata.tables) | {"alembic_version"})
        finally:
            engine.dispose()

    def test_adopts_existing_prototype_without_losing_records(self):
        engine = create_engine("sqlite://")
        try:
            Base.metadata.create_all(engine)
            with Session(engine) as db:
                db.add(User(email="existing@example.com", display_name="Existing", password_hash=hash_password("test-password")))
                db.commit()
            with engine.begin() as connection:
                upgrade_database(connection)
            with Session(engine) as db:
                self.assertEqual(db.query(User).one().email, "existing@example.com")
        finally:
            engine.dispose()

    @unittest.skipUnless(os.getenv("TEST_POSTGRES_URL"), "Requires the disposable CI PostgreSQL database")
    def test_postgres_migration_and_authentication_limits(self):
        # This test never truncates data; it runs only on an explicitly configured test DB.
        engine = create_engine(os.environ["TEST_POSTGRES_URL"])
        try:
            with engine.begin() as connection:
                upgrade_database(connection)
                upgrade_database(connection)
                self.assertEqual(MigrationContext.configure(connection).get_current_revision(), "0003_auth_limits")
            from app.rate_limits import check_auth_limit
            from starlette.requests import Request
            with Session(engine) as db:
                check_auth_limit(db, Request({"type": "http", "client": ("192.0.2.123", 1234)}),
                                 "ci-check@example.com", "login")
        finally:
            engine.dispose()
