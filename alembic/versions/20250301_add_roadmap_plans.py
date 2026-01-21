"""Add roadmap_plans table.

Revision ID: 20250301_add_roadmap_plans
Revises: 20250214_add_flow_stage_and_assumption_fields
Create Date: 2025-03-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "20250301_add_roadmap_plans"
down_revision = "20250214_add_flow_stage_and_assumption_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "roadmap_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("pillar", sa.String(length=50), nullable=False),
        sa.Column("sub_category", sa.String(length=100), nullable=False),
        sa.Column("plan_now", sa.Text(), nullable=True),
        sa.Column("plan_next", sa.Text(), nullable=True),
        sa.Column("plan_later", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("roadmap_plans")
