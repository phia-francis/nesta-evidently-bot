"""Add flow_stage and assumption fields.

Revision ID: 20250214_add_flow_stage_and_assumption_fields
Revises: 20250101_add_project_context_and_mission
Create Date: 2025-02-14 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "20250214_add_flow_stage_and_assumption_fields"
down_revision = "20250101_add_project_context_and_mission"
branch_labels = None
depends_on = None


PROJECT_FLOW_STAGE_ENUM = sa.Enum(
    "audit",
    "plan",
    "action",
    name="project_flow_stage",
    native_enum=False,
)
ASSUMPTION_HORIZON_ENUM = sa.Enum(
    "now",
    "next",
    "later",
    name="assumption_horizon",
    native_enum=False,
)
ASSUMPTION_TEST_PHASE_ENUM = sa.Enum(
    "define",
    "shape",
    "develop",
    "test",
    "scale",
    name="assumption_test_phase",
    native_enum=False,
)


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("flow_stage", PROJECT_FLOW_STAGE_ENUM, nullable=False, server_default="audit"),
    )
    op.add_column(
        "assumptions",
        sa.Column("confidence_score", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "assumptions",
        sa.Column("horizon", ASSUMPTION_HORIZON_ENUM, nullable=True),
    )
    op.add_column(
        "assumptions",
        sa.Column("test_phase", ASSUMPTION_TEST_PHASE_ENUM, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("assumptions", "test_phase")
    op.drop_column("assumptions", "horizon")
    op.drop_column("assumptions", "confidence_score")
    op.drop_column("projects", "flow_stage")
