"""Small additive upgrade for existing prototype databases (SQLite/PostgreSQL)."""

from sqlalchemy import inspect, text


def upgrade_venue_preferences(engine):
    with engine.begin() as connection:
        # Serialize concurrent prototype startup upgrades on PostgreSQL.
        if connection.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(73400321)"))
        inspector = inspect(connection)
        for table, additions in {
            "memberships": {
                "travel_radius_km": "FLOAT NOT NULL DEFAULT 25",
                "allow_places_discovery": "BOOLEAN NOT NULL DEFAULT false",
            },
            "poll_options": {"google_place_id": "VARCHAR(255)"},
        }.items():
            columns = {column["name"] for column in inspector.get_columns(table)}
            for name, definition in additions.items():
                if name not in columns:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
