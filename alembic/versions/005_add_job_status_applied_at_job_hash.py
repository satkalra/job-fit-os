"""add job status, applied_at, job_hash

Revision ID: 005
Revises: 004
Create Date: 2026-06-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("job_results", sa.Column("status", sa.Text(), server_default="new", nullable=False))
    op.add_column("job_results", sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("job_results", sa.Column("job_hash", sa.Text(), nullable=True))
    op.create_index(op.f("ix_job_results_job_hash"), "job_results", ["job_hash"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_job_results_job_hash"), table_name="job_results")
    op.drop_column("job_results", "job_hash")
    op.drop_column("job_results", "applied_at")
    op.drop_column("job_results", "status")
