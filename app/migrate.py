"""Run versioned database upgrades before deploying the web process."""

from alembic import command
from alembic.config import Config

from .config import PROJECT_ROOT


def migration_config():
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    return config


def upgrade_database(connection=None):
    config = migration_config()
    if connection is not None:
        config.attributes["connection"] = connection
    command.upgrade(config, "head")


if __name__ == "__main__":
    upgrade_database()
