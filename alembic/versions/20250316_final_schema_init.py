"""Finalize schema for 5-pillar workflow.

Revision ID: 20250316_final_schema_init
Revises: 20250315_add_diagnostic_schema_updates
Create Date: 2025-03-16 00:00:00.000000
"""

from typing import Any

from alembic import op
import sqlalchemy as sa

revision = "20250316_final_schema_init"
down_revision = "20250315_add_diagnostic_schema_updates"
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


def _column_exists(inspector: Any, table_name: str, column_name: str) -> bool:
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "projects" in table_names and not _column_exists(inspector, "projects", "flow_stage"):
        op.add_column(
            "projects",
            sa.Column("flow_stage", PROJECT_FLOW_STAGE_ENUM, nullable=False, server_default="audit"),
        )

    if "assumptions" in table_names:
        with op.batch_alter_table("assumptions") as batch_op:
            if not _column_exists(inspector, "assumptions", "category"):
                batch_op.add_column(sa.Column("category", sa.Text(), nullable=True))
            if not _column_exists(inspector, "assumptions", "sub_category"):
                batch_op.add_column(sa.Column("sub_category", sa.String(length=100), nullable=True))
            if not _column_exists(inspector, "assumptions", "confidence_score"):
                batch_op.add_column(sa.Column("confidence_score", sa.Integer(), nullable=False, server_default="0"))
            if not _column_exists(inspector, "assumptions", "horizon"):
                batch_op.add_column(sa.Column("horizon", ASSUMPTION_HORIZON_ENUM, nullable=True))
            if _column_exists(inspector, "assumptions", "category"):
                batch_op.alter_column(
                    "category",
                    existing_type=sa.String(length=255),
                    type_=sa.Text(),
                )

    if "roadmap_plans" not in table_names:
        op.create_table(
            "roadmap_plans",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("pillar", sa.String(length=50), nullable=False),
            sa.Column("sub_category", sa.String(length=100), nullable=False),
            sa.Column("plan_now", sa.Text(), nullable=True),
            sa.Column("plan_next", sa.Text(), nullable=True),
            sa.Column("plan_later", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "roadmap_plans" in table_names:
        op.drop_table("roadmap_plans")

    if "assumptions" in table_names:
        with op.batch_alter_table("assumptions") as batch_op:
            if _column_exists(inspector, "assumptions", "horizon"):
                batch_op.drop_column("horizon")
            if _column_exists(inspector, "assumptions", "confidence_score"):
                batch_op.drop_column("confidence_score")
            if _column_exists(inspector, "assumptions", "sub_category"):
                batch_op.drop_column("sub_category")
            if _column_exists(inspector, "assumptions", "category"):
                batch_op.drop_column("category")

    if "projects" in table_names and _column_exists(inspector, "projects", "flow_stage"):
        op.drop_column("projects", "flow_stage")
