"""add preferred_locations drop remote_only

Revision ID: 002
Revises: 001
Create Date: 2026-05-17
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column("preferred_locations", postgresql.ARRAY(sa.Text()), nullable=True),
    )
    op.drop_column("user_profiles", "remote_only")


def downgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column("remote_only", sa.Boolean(), server_default="false", nullable=False),
    )
    op.drop_column("user_profiles", "preferred_locations")
