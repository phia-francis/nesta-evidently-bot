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

def _column_exists(inspector: Any, table_name: str, column_name: str) -> bool:
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "assumptions" in table_names:
        with op.batch_alter_table("assumptions") as batch_op:
            if not _column_exists(inspector, "assumptions", "sub_category"):
                batch_op.add_column(sa.Column("sub_category", sa.String(length=100), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "assumptions" in table_names:
        with op.batch_alter_table("assumptions") as batch_op:
            if _column_exists(inspector, "assumptions", "sub_category"):
                batch_op.drop_column("sub_category")
