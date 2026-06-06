"""add countries and needs_sponsorship

Revision ID: 003
Revises: 002
Create Date: 2026-05-31
"""
import sqlalchemy as sa
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS countries TEXT[]")
    op.execute(
        "ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS needs_sponsorship BOOLEAN NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE user_profiles DROP COLUMN IF EXISTS needs_sponsorship")
    op.execute("ALTER TABLE user_profiles DROP COLUMN IF EXISTS countries")
