from alembic import context
from sqlalchemy import text

from app.db import Base, engine
from app import models  # Register all mapped tables for autogeneration.

config = context.config


def migrate(connection):
    context.configure(connection=connection, target_metadata=Base.metadata,
                      compare_type=True, render_as_batch=connection.dialect.name == "sqlite")
    with context.begin_transaction():
        if connection.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(73400321)"))
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("These migrations require an online database connection.")
elif config.attributes.get("connection") is not None:
    migrate(config.attributes["connection"])
else:
    with engine.connect() as connection:
        migrate(connection)
