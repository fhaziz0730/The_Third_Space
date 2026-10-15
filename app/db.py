import os

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase

from .config import PROJECT_ROOT, is_mock_mode

USE_MOCK_DATA = is_mock_mode()
MOCK_DATABASE_PATH = PROJECT_ROOT / ".mock" / "third_space.db"
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://third_space:third_space@localhost:5432/third_space",
)
if USE_MOCK_DATA:
    MOCK_DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATABASE_URL = f"sqlite:///{MOCK_DATABASE_PATH.as_posix()}"
elif DATABASE_URL.startswith(("postgres://", "postgresql://")):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL.split("://", 1)[1]
connect_args = {}
if DATABASE_URL.startswith("sqlite:"):
    connect_args["check_same_thread"] = False
elif DATABASE_URL.startswith("postgresql+"):
    connect_args["connect_timeout"] = 5
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)


class Base(DeclarativeBase):
    pass


def get_db(request: Request):
    with request.app.state.sessions() as db:
        yield db
