"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("email", sa.Text(), unique=True, nullable=False),
        sa.Column("name", sa.Text()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_table(
        "user_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("profile_type", sa.Text(), nullable=False),
        sa.Column("resume_text", sa.Text()),
        sa.Column("resume_pdf_name", sa.Text()),
        sa.Column("domains", postgresql.ARRAY(sa.Text())),
        sa.Column("keywords", sa.Text()),
        sa.Column("seniority", sa.Text()),
        sa.Column("min_salary", sa.Integer()),
        sa.Column("remote_only", sa.Boolean(), server_default="false"),
        sa.Column("target_companies", postgresql.JSONB()),
        sa.Column("active", sa.Boolean(), server_default="true"),
        sa.Column("briefing_time", sa.Text(), server_default="'07:00'"),
        sa.Column("timezone", sa.Text(), server_default="'America/New_York'"),
        sa.Column("weight_role_match", sa.Float(), server_default="0.30"),
        sa.Column("weight_skills_match", sa.Float(), server_default="0.30"),
        sa.Column("weight_experience_level", sa.Float(), server_default="0.20"),
        sa.Column("weight_compensation", sa.Float(), server_default="0.10"),
        sa.Column("weight_cultural", sa.Float(), server_default="0.10"),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_table(
        "job_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column("company", sa.Text()),
        sa.Column("location", sa.Text()),
        sa.Column("posted_date", sa.Text()),
        sa.Column("salary", sa.Text()),
        sa.Column("description", sa.Text()),
        sa.Column("requirements", postgresql.ARRAY(sa.Text())),
        sa.Column("tags", postgresql.ARRAY(sa.Text())),
        sa.Column("url", sa.Text()),
        sa.Column("source", sa.Text()),
        sa.Column("global_score", sa.Integer()),
        sa.Column("verdict", sa.Text()),
        sa.Column("scores", postgresql.JSONB()),
        sa.Column("red_flags", postgresql.JSONB()),
        sa.Column("citations", postgresql.JSONB()),
        sa.Column("summary", sa.Text()),
        sa.Column("rewrite_token", sa.Text(), unique=True),
        sa.Column("rewrite_sent_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )


def downgrade() -> None:
    op.drop_table("job_results")
    op.drop_table("user_profiles")
    op.drop_table("users")
