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
    op.execute("ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS preferred_locations TEXT[]")
    op.execute("ALTER TABLE user_profiles DROP COLUMN IF EXISTS remote_only")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS remote_only BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute("ALTER TABLE user_profiles DROP COLUMN IF EXISTS preferred_locations")
