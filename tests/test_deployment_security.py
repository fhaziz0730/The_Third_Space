from datetime import datetime, timedelta, timezone
import os
import re
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from starlette.requests import Request
from starlette.testclient import TestClient

from app.config import Settings
from app.db import Base, get_db
from app.main import create_app
from app.migrate import upgrade_database
from app.models import AuthRateLimit, User
from app.rate_limits import check_auth_limit


class SecurityHTTPTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        with self.engine.begin() as connection:
            upgrade_database(connection)
        self.app = create_app(Settings(False, "test-secret-with-enough-random-characters", False, "http://testserver", ("testserver",)))

        def database():
            with Session(self.engine) as db:
                yield db

        self.app.dependency_overrides[get_db] = database
        # Avoid lifespan: this suite uses an isolated migrated database above.
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def token(self, path="/register"):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        return re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)

    def test_missing_invalid_and_cross_origin_tokens_rejected_before_mutation(self):
        token = self.token()
        fields = {"email": "person@example.com", "display_name": "Person", "password": "test-password"}
        self.assertEqual(self.client.post("/register", data=fields).status_code, 403)
        self.assertEqual(self.client.post("/register", data={**fields, "csrf_token": "invalid"}).status_code, 403)
        self.assertEqual(self.client.post("/register", data={**fields, "csrf_token": token},
                                          headers={"Origin": "https://attacker.example"}).status_code, 403)
        self.assertEqual(self.client.post("/register", data={**fields, "csrf_token": token},
                                          headers={"Origin": "null"}).status_code, 403)
        self.assertEqual(self.client.post("/register", data={**fields, "csrf_token": token},
                                          headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
        with Session(self.engine) as db:
            self.assertEqual(db.query(User).count(), 0)

    def test_form_body_is_replayed_and_csrf_rotates_after_sign_in(self):
        token = self.token()
        response = self.client.post("/register", data={"email": "person@example.com", "display_name": "Person",
                                                       "password": "test-password", "csrf_token": token},
                                    headers={"Origin": "http://testserver"}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.client.post("/logout", data={"csrf_token": token}).status_code, 403)
        new_token = self.token("/")
        self.assertNotEqual(new_token, token)
        self.assertEqual(self.client.post("/logout", data={"csrf_token": new_token}).status_code, 200)

    def test_ajax_header_and_origin_validation(self):
        token = self.token()
        # A valid token passes middleware and reaches membership authorization.
        response = self.client.post("/groups/1/location-search", data={"q": "Boston"},
                                    headers={"X-CSRF-Token": token})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.post("/groups/1/location-search", data={"q": "Boston"}).status_code, 403)

    def test_security_headers_hosts_and_readiness(self):
        response = self.client.get("/login")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("form-action 'self'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(self.client.get("/", headers={"Host": "attacker.example"}).status_code, 400)
        self.assertEqual(self.client.get("/health/live").status_code, 200)
        self.assertEqual(self.client.get("/health/ready").status_code, 200)
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num = 'older-revision'"))
        self.assertEqual(self.client.get("/health/ready").status_code, 503)

    def test_form_request_size_limit(self):
        self.token()
        response = self.client.post("/register", content=b"x=" + b"a" * (256 * 1024),
                                    headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(response.status_code, 413)


class ProductionConfigTests(unittest.TestCase):
    def environment(self):
        return {"APP_ENV": "production", "SESSION_SECRET": "a-long-random-test-secret-of-40-characters",
                "COOKIE_SECURE": "true", "APP_ORIGIN": "https://example.com", "ALLOWED_HOSTS": "example.com,healthcheck.railway.app",
                "USE_MOCK_DATA": "false", "DATABASE_URL": "postgresql+psycopg://user:password@host/db?sslmode=require",
                "ADDRESS_ENCRYPTION_KEY": Fernet.generate_key().decode()}

    def test_valid_and_unsafe_configuration(self):
        with patch.dict(os.environ, self.environment(), clear=True):
            self.assertTrue(Settings.from_env().production)
        for name, value in (("SESSION_SECRET", "development-only-change-me"), ("COOKIE_SECURE", "false"),
                            ("APP_ORIGIN", "http://example.com"), ("ALLOWED_HOSTS", "*"),
                            ("USE_MOCK_DATA", "true"), ("ADDRESS_ENCRYPTION_KEY", "invalid"),
                            ("DATABASE_URL", "sqlite:///app.db")):
            with self.subTest(name=name), patch.dict(os.environ, {**self.environment(), name: value}, clear=True):
                with self.assertRaises(ValueError):
                    Settings.from_env()


class RateLimitTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def request(self, address):
        return Request({"type": "http", "client": (address, 1234)})

    def test_email_limit_shared_across_ip_addresses_and_session_instances(self):
        for index in range(10):
            check_auth_limit(self.db, self.request(f"192.0.2.{index}"), "TEST@example.com", "login")
        with Session(self.engine) as other:
            with self.assertRaises(HTTPException) as raised:
                check_auth_limit(other, self.request("192.0.2.200"), "test@example.com", "login")
        self.assertEqual(raised.exception.status_code, 429)
        self.assertGreater(int(raised.exception.headers["Retry-After"]), 0)

    def test_registration_ip_limit_and_expiry(self):
        for index in range(5):
            check_auth_limit(self.db, self.request("192.0.2.1"), f"person{index}@example.com", "register")
        with self.assertRaises(HTTPException):
            check_auth_limit(self.db, self.request("192.0.2.1"), "new@example.com", "register")
        for row in self.db.scalars(select(AuthRateLimit)):
            row.window_started = datetime.now(timezone.utc) - timedelta(hours=2)
        self.db.commit()
        check_auth_limit(self.db, self.request("192.0.2.1"), "new@example.com", "register")
