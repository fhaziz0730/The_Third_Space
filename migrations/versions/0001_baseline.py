"""Freeze the original prototype schema and adopt complete existing databases."""
from alembic import op
import sqlalchemy as sa

revision = "0001_baseline"
down_revision = None
branch_labels = depends_on = None


def baseline():
    m = sa.MetaData()
    sa.Table("users", m, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("email", sa.String(254), nullable=False, unique=True, index=True),
             sa.Column("display_name", sa.String(80), nullable=False),
             sa.Column("password_hash", sa.String(256), nullable=False),
             sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    sa.Table("groups", m, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("name", sa.String(100), nullable=False),
             sa.Column("description", sa.String(500), nullable=False),
             sa.Column("hobbies", sa.String(1000), nullable=False),
             sa.Column("is_private", sa.Boolean, nullable=False), sa.Column("member_limit", sa.Integer),
             sa.Column("owner_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
             sa.Column("join_token", sa.String(64), unique=True, index=True, nullable=False),
             sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    sa.Table("memberships", m, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("group_id", sa.Integer, sa.ForeignKey("groups.id"), nullable=False),
             sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
             sa.Column("role", sa.String(16), nullable=False),
             sa.Column("hobbies", sa.String(1000), nullable=False),
             sa.Column("timezone_name", sa.String(64), nullable=False),
             sa.Column("broad_location", sa.String(160), nullable=False),
             sa.Column("exact_address_ciphertext", sa.String(700), nullable=False),
             sa.Column("latitude", sa.Float), sa.Column("longitude", sa.Float),
             sa.Column("hide_hobbies", sa.Boolean, nullable=False),
             sa.Column("hide_availability", sa.Boolean, nullable=False),
             sa.Column("hide_location", sa.Boolean, nullable=False),
             sa.UniqueConstraint("group_id", "user_id"))
    sa.Table("availability_windows", m, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("membership_id", sa.Integer, sa.ForeignKey("memberships.id"), nullable=False),
             sa.Column("weekday", sa.Integer, nullable=False),
             sa.Column("starts_at", sa.Time, nullable=False), sa.Column("ends_at", sa.Time, nullable=False))
    sa.Table("places", m, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("name", sa.String(120), nullable=False),
             sa.Column("activity_tag", sa.String(60), index=True, nullable=False),
             sa.Column("broad_location", sa.String(160), nullable=False),
             sa.Column("latitude", sa.Float, nullable=False), sa.Column("longitude", sa.Float, nullable=False),
             sa.Column("description", sa.String(300), nullable=False))
    sa.Table("polls", m, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("group_id", sa.Integer, sa.ForeignKey("groups.id"), nullable=False),
             sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
             sa.Column("closes_at", sa.DateTime(timezone=True), nullable=False),
             sa.Column("closed_at", sa.DateTime(timezone=True)),
             sa.Column("confirmed_option_id", sa.Integer,
                       sa.ForeignKey("poll_options.id", name="fk_polls_confirmed_option", use_alter=True)),
             sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    sa.Table("poll_options", m, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("poll_id", sa.Integer, sa.ForeignKey("polls.id"), nullable=False),
             sa.Column("activity", sa.String(120), nullable=False),
             sa.Column("duration_minutes", sa.Integer, nullable=False),
             sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
             sa.Column("place_id", sa.Integer, sa.ForeignKey("places.id")),
             sa.Column("available_user_ids", sa.String(1000), nullable=False))
    sa.Table("votes", m, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("option_id", sa.Integer, sa.ForeignKey("poll_options.id"), nullable=False),
             sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
             sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
             sa.UniqueConstraint("option_id", "user_id"))
    sa.Table("rsvps", m, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("option_id", sa.Integer, sa.ForeignKey("poll_options.id"), nullable=False),
             sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
             sa.Column("response", sa.String(16), nullable=False), sa.UniqueConstraint("option_id", "user_id"))
    return m


def upgrade():
    connection = op.get_bind()
    schema = baseline()
    inspector = sa.inspect(connection)
    existing = set(inspector.get_table_names()) & set(schema.tables)
    if existing and existing != set(schema.tables):
        raise RuntimeError("Incomplete prototype schema. Restore or repair it before migrating.")
    for table in existing:
        actual = {column["name"] for column in inspector.get_columns(table)}
        if not set(schema.tables[table].columns.keys()) <= actual:
            raise RuntimeError(f"Unexpected schema in {table}; review before adopting migrations.")
    schema.create_all(connection, checkfirst=True)


def downgrade():
    raise RuntimeError("Baseline downgrade is destructive. Restore a verified backup instead.")
