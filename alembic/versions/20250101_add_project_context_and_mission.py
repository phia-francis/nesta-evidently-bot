"""Add mission and context_summary to projects.

Revision ID: 20250101_add_project_context_and_mission
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "20250101_add_project_context_and_mission"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("mission", sa.Text(), nullable=True))
    op.add_column("projects", sa.Column("context_summary", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "context_summary")
    op.drop_column("projects", "mission")
