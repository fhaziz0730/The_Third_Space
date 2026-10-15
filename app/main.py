import os

from fastapi import Depends, FastAPI, Request
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from .db import Base, SessionLocal, USE_MOCK_DATA, engine, get_db
from .routes import auth, groups, places, polls
from .web import current_user, page

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


@app.get("/privacy")
def privacy_page(request: Request, db: Session = Depends(get_db)):
    return page(request, "privacy.html", user=current_user(request, db))


@app.get("/terms")
def terms_page(request: Request, db: Session = Depends(get_db)):
    return page(request, "terms.html", user=current_user(request, db))


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    from .schema import upgrade_venue_preferences

    upgrade_venue_preferences(engine)
    if USE_MOCK_DATA:
        from .mock_data import seed_mock_data

        with SessionLocal() as db:
            seed_mock_data(db)
