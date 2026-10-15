"""Deployment settings with explicit production guardrails."""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def is_mock_mode():
    return os.getenv("USE_MOCK_DATA", "false").lower() == "true"


@dataclass(frozen=True)
class Settings:
    production: bool
    session_secret: str
    cookie_secure: bool
    app_origin: str
    allowed_hosts: tuple[str, ...]

    @classmethod
    def from_env(cls):
        environment = os.getenv("APP_ENV", "development")
        if environment not in {"development", "test", "production"}:
            raise ValueError("APP_ENV must be development, test, or production.")
        production = environment == "production"
        secret = os.getenv("SESSION_SECRET", "development-only-change-me")
        secure = os.getenv("COOKIE_SECURE", "false").lower() == "true"
        origin = os.getenv("APP_ORIGIN", "").rstrip("/")
        hosts = tuple(
            h.strip()
            for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")
            if h.strip()
        )
        if production:
            if len(secret) < 32 or secret in {
                "replace-this-with-a-long-random-value",
                "development-only-change-me",
                "GENERATE_A_RANDOM_SECRET_OF_AT_LEAST_32_CHARACTERS",
            }:
                raise ValueError(
                    "Production requires a random SESSION_SECRET of at least 32 characters."
                )
            if not secure:
                raise ValueError("Production requires COOKIE_SECURE=true.")
            parsed = urlsplit(origin)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username
            ):
                raise ValueError(
                    "Production requires APP_ORIGIN=https://your-app-host with no path."
                )
            if "*" in hosts or parsed.hostname not in hosts:
                raise ValueError(
                    "ALLOWED_HOSTS must include the app hostname and must not contain '*'."
                )
            if is_mock_mode():
                raise ValueError(
                    "Production cannot use shared mock accounts. Set USE_MOCK_DATA=false."
                )
            if not os.getenv("DATABASE_URL", "").startswith(
                ("postgresql://", "postgres://", "postgresql+psycopg://")
            ):
                raise ValueError("Production requires an explicit PostgreSQL DATABASE_URL.")
            if make_url(os.environ["DATABASE_URL"]).query.get("sslmode") not in {
                "require",
                "verify-ca",
                "verify-full",
            }:
                raise ValueError(
                    "Production DATABASE_URL must enable TLS with sslmode=require or stronger."
                )
            try:
                Fernet(os.environ["ADDRESS_ENCRYPTION_KEY"].encode())
            except (KeyError, ValueError, TypeError) as exc:
                raise ValueError(
                    "Production requires a valid Fernet ADDRESS_ENCRYPTION_KEY."
                ) from exc
        return cls(production, secret, secure, origin, hosts)
