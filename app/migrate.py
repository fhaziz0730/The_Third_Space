"""Run versioned database upgrades before deploying the web process."""

from pathlib import Path

from alembic import command
from alembic.config import Config


def migration_config():
    root = Path(__file__).resolve().parent.parent
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    return config


def upgrade_database(connection=None):
    config = migration_config()
    if connection is not None:
        config.attributes["connection"] = connection
    command.upgrade(config, "head")


if __name__ == "__main__":
    upgrade_database()
