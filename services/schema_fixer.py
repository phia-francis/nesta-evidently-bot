import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import SQLAlchemyError

from config import Config


logger = logging.getLogger(__name__)


def _build_engine():
    url = make_url(Config.DATABASE_URL)
    connect_args = {}

    if url.drivername.startswith("postgresql") or url.drivername == "postgres":
        url = url.set(drivername="postgresql+psycopg2")
        if not url.query.get("sslmode"):
            connect_args["sslmode"] = "require"

    return create_engine(url, connect_args=connect_args, pool_pre_ping=True)


def _safe_execute(connection, statement: str, context: str) -> None:
    try:
        connection.execute(text(statement))
    except SQLAlchemyError as exc:
        logger.exception("Schema update skipped for %s: %s", context, exc)


def _build_default_clause(default_value: str | int | None) -> str:
    if default_value is None:
        return ""
    if isinstance(default_value, str):
        return f" DEFAULT '{default_value}'"
    return f" DEFAULT {default_value}"


def _add_column_if_missing(
    connection,
    table_name: str,
    column_name: str,
    column_type: str,
    default_value: str | int | None = None,
) -> None:
    inspector = inspect(connection)
    table_column_names = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name in table_column_names:
        return
    default_clause = _build_default_clause(default_value)
    statement = (
        f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}{default_clause}"
    )
    _safe_execute(connection, statement, f"{table_name}.{column_name}")


def check_and_update_schema() -> None:
    engine = _build_engine()
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    with engine.begin() as connection:
        if "projects" in table_names:
            _add_column_if_missing(connection, "projects", "flow_stage", "VARCHAR(50)", "audit")
            _add_column_if_missing(connection, "projects", "mission", "TEXT")
            _add_column_if_missing(connection, "projects", "dashboard_message_ts", "VARCHAR(50)")

        if "assumptions" in table_names:
            _add_column_if_missing(connection, "assumptions", "category", "TEXT")
            _add_column_if_missing(connection, "assumptions", "sub_category", "VARCHAR(100)")
            _add_column_if_missing(connection, "assumptions", "horizon", "VARCHAR(20)")
            _add_column_if_missing(connection, "assumptions", "confidence_score", "INTEGER", 0)
            _add_column_if_missing(connection, "assumptions", "plan_now", "TEXT")
            _add_column_if_missing(connection, "assumptions", "plan_next", "TEXT")
            _add_column_if_missing(connection, "assumptions", "plan_later", "TEXT")
            _add_column_if_missing(connection, "assumptions", "owner_id", "VARCHAR(50)")
            _add_column_if_missing(connection, "assumptions", "test_phase", "VARCHAR(50)")
            _add_column_if_missing(connection, "assumptions", "test_and_learn_phase", "VARCHAR(50)")

        if "experiments" in table_names:
            _add_column_if_missing(connection, "experiments", "kpi_target", "FLOAT")
            _add_column_if_missing(connection, "experiments", "kpi_actual", "FLOAT")

        if "roadmap_plans" not in table_names:
            timestamp_type = (
                "TIMESTAMP"
                if engine.dialect.name in {"postgresql", "postgres"}
                else "DATETIME"
            )
            _safe_execute(
                connection,
                """
                CREATE TABLE roadmap_plans (
                    id INTEGER PRIMARY KEY,
                    project_id INTEGER REFERENCES projects(id),
                    pillar VARCHAR(50),
                    sub_category VARCHAR(100),
                    plan_now TEXT,
                    plan_next TEXT,
                    plan_later TEXT,
                    updated_at {timestamp_type} DEFAULT CURRENT_TIMESTAMP
                )
                """.format(timestamp_type=timestamp_type),
                "roadmap_plans",
            )
