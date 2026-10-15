from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .access import current_user
from .config import PROJECT_ROOT, Settings
from .csrf import CSRFMiddleware
from .db import USE_MOCK_DATA, engine, get_db
from .routes import auth, groups, places, polls, profiles
from .web import page


def create_app(settings=None, *, database_engine=None):
    settings = settings or Settings.from_env()
    database_engine = database_engine or engine
    sessions = sessionmaker(bind=database_engine, autoflush=False, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(app):
        if not settings.production:
            from .migrate import upgrade_database

            with database_engine.begin() as connection:
                upgrade_database(connection)
            if USE_MOCK_DATA:
                from .mock_data import seed_mock_data

                with sessions() as db:
                    seed_mock_data(db)
        yield

    app = FastAPI(
        title="The Third Space",
        lifespan=lifespan,
        docs_url=None if settings.production else "/docs",
        redoc_url=None if settings.production else "/redoc",
    )
    app.state.sessions = sessions
    app.add_middleware(CSRFMiddleware, app_origin=settings.app_origin)
    # SessionMiddleware must wrap CSRF so the signed session is available there.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        same_site="lax",
        https_only=settings.cookie_secure,
        max_age=60 * 60 * 24 * 7,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(self)"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'self'; form-action 'self'"
        )
        if settings.production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "app" / "static"), name="static")
    for router in (auth.router, groups.router, profiles.router, polls.router, places.router):
        app.include_router(router)

    @app.get("/health/live", include_in_schema=False)
    def live():
        return {"status": "ok"}

    @app.get("/health/ready", include_in_schema=False)
    def ready(db: Session = Depends(get_db)):
        try:
            # Reading an application table also detects missing migrations.
            db.execute(text("SELECT 1 FROM users LIMIT 1"))
            from alembic.runtime.migration import MigrationContext
            from alembic.script import ScriptDirectory

            from .migrate import migration_config

            current = MigrationContext.configure(db.connection()).get_current_heads()
            expected = ScriptDirectory.from_config(migration_config()).get_heads()
            if set(current) != set(expected):
                raise RuntimeError("Database schema is not current")
        except Exception:
            db.rollback()
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return {"status": "ok"}

    @app.get("/privacy")
    def privacy_page(request: Request, db: Session = Depends(get_db)):
        return page(request, "privacy.html", user=current_user(request, db))

    @app.get("/terms")
    def terms_page(request: Request, db: Session = Depends(get_db)):
        return page(request, "terms.html", user=current_user(request, db))

    return app


app = create_app()
