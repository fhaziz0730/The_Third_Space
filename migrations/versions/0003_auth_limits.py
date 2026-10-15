"""Shared authentication throttling counters."""
from alembic import op
import sqlalchemy as sa

revision = "0003_auth_limits"
down_revision = "0002_venues"
branch_labels = depends_on = None


def upgrade():
    if "auth_rate_limits" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table("auth_rate_limits", sa.Column("bucket", sa.String(64), primary_key=True),
                        sa.Column("window_started", sa.DateTime(timezone=True), nullable=False),
                        sa.Column("attempts", sa.Integer, nullable=False))


def downgrade():
    raise RuntimeError("Use a forward migration or restore a verified backup.")
