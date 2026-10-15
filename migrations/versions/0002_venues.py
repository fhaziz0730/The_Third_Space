"""Add venue preferences, preserving upgrades from the earlier prototype."""
from alembic import op
import sqlalchemy as sa

revision = "0002_venues"
down_revision = "0001_baseline"
branch_labels = depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    for table, columns in {
        "memberships": [sa.Column("travel_radius_km", sa.Float, nullable=False, server_default="25"),
                        sa.Column("allow_places_discovery", sa.Boolean, nullable=False, server_default=sa.false())],
        "poll_options": [sa.Column("google_place_id", sa.String(255))],
    }.items():
        existing = {column["name"] for column in inspector.get_columns(table)}
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)


def downgrade():
    raise RuntimeError("Restore a verified backup instead of dropping venue preferences.")
