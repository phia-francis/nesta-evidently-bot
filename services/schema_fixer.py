import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import SQLAlchemyError


def _build_engine():
    database_url = os.getenv("DATABASE_URL", "sqlite:///./evidently.db")
    url = make_url(database_url)
    connect_args = {}

    if url.drivername.startswith("postgresql") or url.drivername == "postgres":
        url = url.set(drivername="postgresql+psycopg2")
        if not url.query.get("sslmode"):
            connect_args["sslmode"] = "require"

    return create_engine(url, connect_args=connect_args, pool_pre_ping=True)


def _safe_execute(connection, statement: str) -> None:
    try:
        connection.execute(text(statement))
    except SQLAlchemyError as exc:
        print(f"Schema update skipped: {exc}")


def check_and_update_schema() -> None:
    engine = _build_engine()
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    with engine.begin() as connection:
        if "projects" in table_names:
            project_columns = {column["name"] for column in inspector.get_columns("projects")}
            if "flow_stage" not in project_columns:
                _safe_execute(
                    connection,
                    "ALTER TABLE projects ADD COLUMN flow_stage VARCHAR(50) DEFAULT 'audit'",
                )

        if "assumptions" in table_names:
            assumption_columns = {column["name"] for column in inspector.get_columns("assumptions")}
            if "sub_category" not in assumption_columns:
                _safe_execute(
                    connection,
                    "ALTER TABLE assumptions ADD COLUMN sub_category VARCHAR(100)",
                )
            if "horizon" not in assumption_columns:
                _safe_execute(
                    connection,
                    "ALTER TABLE assumptions ADD COLUMN horizon VARCHAR(20)",
                )
            if "confidence_score" not in assumption_columns:
                _safe_execute(
                    connection,
                    "ALTER TABLE assumptions ADD COLUMN confidence_score INTEGER DEFAULT 0",
                )
            if "plan_now" not in assumption_columns:
                _safe_execute(
                    connection,
                    "ALTER TABLE assumptions ADD COLUMN plan_now TEXT",
                )
            if "plan_next" not in assumption_columns:
                _safe_execute(
                    connection,
                    "ALTER TABLE assumptions ADD COLUMN plan_next TEXT",
                )
            if "plan_later" not in assumption_columns:
                _safe_execute(
                    connection,
                    "ALTER TABLE assumptions ADD COLUMN plan_later TEXT",
                )
            if "owner_id" not in assumption_columns:
                _safe_execute(
                    connection,
                    "ALTER TABLE assumptions ADD COLUMN owner_id VARCHAR(50)",
                )
            if "test_phase" not in assumption_columns:
                _safe_execute(
                    connection,
                    "ALTER TABLE assumptions ADD COLUMN test_phase VARCHAR(50)",
                )

        if "experiments" in table_names:
            experiment_columns = {column["name"] for column in inspector.get_columns("experiments")}
            if "kpi_target" not in experiment_columns:
                _safe_execute(
                    connection,
                    "ALTER TABLE experiments ADD COLUMN kpi_target FLOAT",
                )
            if "kpi_actual" not in experiment_columns:
                _safe_execute(
                    connection,
                    "ALTER TABLE experiments ADD COLUMN kpi_actual FLOAT",
                )

        if "roadmap_plans" not in table_names:
            _safe_execute(
                connection,
                """
                CREATE TABLE roadmap_plans (
                    id INTEGER PRIMARY KEY,
                    project_id INTEGER,
                    pillar VARCHAR(50),
                    sub_category VARCHAR(100),
                    plan_now TEXT,
                    plan_next TEXT,
                    plan_later TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """,
            )
