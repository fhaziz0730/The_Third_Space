import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .db import Base, engine
from .routes import auth, groups, places, polls

app = FastAPI(title="The Third Space")
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "development-only-change-me"),
    same_site="lax",
    https_only=os.getenv("COOKIE_SECURE", "false").lower() == "true",
)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router)
app.include_router(groups.router)
app.include_router(polls.router)
app.include_router(places.router)


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
