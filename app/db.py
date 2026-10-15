import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


USE_MOCK_DATA = os.getenv("USE_MOCK_DATA", "false").lower() == "true"
MOCK_DATABASE_PATH = Path(__file__).resolve().parent.parent / ".mock" / "third_space.db"
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://third_space:third_space@localhost:5432/third_space",
)
if USE_MOCK_DATA:
    MOCK_DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATABASE_URL = f"sqlite:///{MOCK_DATABASE_PATH.as_posix()}"
elif DATABASE_URL.startswith(("postgres://", "postgresql://")):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL.split("://", 1)[1]
engine = create_engine(
    DATABASE_URL, pool_pre_ping=True,
    **({"connect_args": {"check_same_thread": False}} if USE_MOCK_DATA else
       {"connect_args": {"connect_timeout": 5}} if DATABASE_URL.startswith("postgresql+") else {}),
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
