"""Atomic database-backed limits shared by all app instances."""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import math
import os

from fastapi import HTTPException
from sqlalchemy import case, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .models import AuthRateLimit


def check_auth_limit(db, request, email, action):
    now = datetime.now(timezone.utc)
    address = request.client.host if request.client else "unknown"
    rules = [(f"{action}:ip:{address}", 20 if action == "login" else 5, 900 if action == "login" else 3600)]
    if action == "login":
        rules.append((f"login:email:{email.strip().lower()}", 10, 900))
    secret = os.getenv("SESSION_SECRET", "development-only-change-me").encode()
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    db.execute(delete(AuthRateLimit).where(AuthRateLimit.window_started < now - timedelta(days=1)))
    for identity, limit, seconds in rules:
        bucket = hmac.new(secret, identity.encode(), hashlib.sha256).hexdigest()
        expired = AuthRateLimit.window_started <= now - timedelta(seconds=seconds)
        statement = insert(AuthRateLimit).values(bucket=bucket, window_started=now, attempts=1)
        statement = statement.on_conflict_do_update(index_elements=[AuthRateLimit.bucket], set_={
            "attempts": case((expired, 1), else_=AuthRateLimit.attempts + 1),
            "window_started": case((expired, now), else_=AuthRateLimit.window_started),
        }).returning(AuthRateLimit.attempts, AuthRateLimit.window_started)
        count, started = db.execute(statement).one()
        if count > limit:
            db.commit()
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            retry = max(1, math.ceil((started + timedelta(seconds=seconds) - now).total_seconds()))
            raise HTTPException(429, "Too many attempts. Please try again later.", headers={"Retry-After": str(retry)})
    db.commit()
