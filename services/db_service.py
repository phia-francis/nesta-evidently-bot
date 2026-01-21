import datetime as dt
import logging
import os
import secrets
from collections import defaultdict
from typing import Any, Dict, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    create_engine,
    func,
    inspect,
    or_,
    text,
)
from sqlalchemy.engine.url import make_url
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, declarative_base, joinedload, relationship, sessionmaker

from cryptography.fernet import Fernet, InvalidToken

from config import Config
from constants import VALID_ASSUMPTION_CATEGORIES
from services.toolkit_service import ToolkitService

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./evidently.db")

ASSUMPTION_CATEGORY_ENUM = Enum(
    *VALID_ASSUMPTION_CATEGORIES,
    name="assumption_category",
    native_enum=False,
)
ASSUMPTION_STATUS_ENUM = Enum(
    "Testing",
    "Validated",
    "Rejected",
    name="assumption_status",
    native_enum=False,
)
PROJECT_FLOW_STAGE_ENUM = Enum(
    "audit",
    "plan",
    "action",
    name="project_flow_stage",
    native_enum=False,
)
ASSUMPTION_HORIZON_ENUM = Enum(
    "now",
    "next",
    "later",
    name="assumption_horizon",
    native_enum=False,
)
TEST_AND_LEARN_PHASE_ENUM = Enum(
    "define",
    "shape",
    "develop",
    "test",
    "scale",
    name="test_and_learn_phase",
    native_enum=False,
)
ASSUMPTION_TEST_PHASE_ENUM = Enum(
    "define",
    "shape",
    "develop",
    "test",
    "scale",
    name="assumption_test_phase",
    native_enum=False,
)


def _build_engine() -> Engine:
    url = make_url(DATABASE_URL)
    connect_args = {}

    if url.drivername.startswith("postgresql") or url.drivername == "postgres":
        url = url.set(drivername="postgresql+psycopg2")
        if not url.query.get("sslmode"):
            connect_args["sslmode"] = "require"

    return create_engine(url, connect_args=connect_args, pool_pre_ping=True)


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255))
    description = Column(Text)
    mission = Column(Text, nullable=True)
    context_summary = Column(Text, nullable=True)
    status = Column(String(50), default="active")
    stage = Column(String(50), default="Define")
    flow_stage = Column(PROJECT_FLOW_STAGE_ENUM, default="audit")
    channel_id = Column(String(50))
    created_by = Column(String(50))
    created_at = Column(DateTime, default=dt.datetime.utcnow)
    google_access_token = Column(Text, nullable=True)
    google_refresh_token = Column(Text, nullable=True)
    token_expiry = Column(DateTime, nullable=True)
    dashboard_message_ts = Column(String(50), nullable=True)

    integrations = Column(
        JSON,
        default=lambda: {
            "drive": {"connected": False, "folder_id": None},
            "calendar": {"connected": False},
            "asana": {"connected": False, "project_id": None},
            "miro": {"connected": False, "board_url": None},
        },
    )

    canvas_items = relationship("CanvasItem", back_populates="project", cascade="all, delete-orphan")
    experiments = relationship("Experiment", back_populates="project", cascade="all, delete-orphan")
    assumptions = relationship("Assumption", back_populates="project", cascade="all, delete-orphan")
    members = relationship("ProjectMember", back_populates="project", cascade="all, delete-orphan")
    decisions = relationship("DecisionSession", back_populates="project")
    collections = relationship("Collection", back_populates="project", cascade="all, delete-orphan")
    automation_rules = relationship("AutomationRule", back_populates="project", cascade="all, delete-orphan")
    roadmap_plans = relationship("RoadmapPlan", back_populates="project", cascade="all, delete-orphan")


class ProjectMember(Base):
    __tablename__ = "project_members"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    user_id = Column(String(50))
    role = Column(String(50), default="member")
    project = relationship("Project", back_populates="members")


class CanvasItem(Base):
    """Stores items for Opportunity, Capability, Feasibility, Progress."""

    __tablename__ = "canvas_items"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))

    section = Column(String(50))
    text = Column(Text)
    ai_generated = Column(Boolean, default=False)

    project = relationship("Project", back_populates="canvas_items")


class Collection(Base):
    """Groups of experiments or assumptions (e.g., 'Q1 Priorities')."""

    __tablename__ = "collections"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    name = Column(String(255))
    description = Column(Text, nullable=True)

    project = relationship("Project", back_populates="collections")


class AutomationRule(Base):
    """Rules like 'If Experiment Created -> Notify #channel'."""

    __tablename__ = "automation_rules"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    trigger_event = Column(String(100))
    action_type = Column(String(100))
    is_active = Column(Boolean, default=True)

    project = relationship("Project", back_populates="automation_rules")


class Experiment(Base):
    __tablename__ = "experiments"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    assumption_id = Column(Integer, ForeignKey("assumptions.id"), nullable=True)

    title = Column(String(255))
    hypothesis = Column(Text)
    method = Column(String(100))
    stage = Column(String(50))
    status = Column(String(50), default="planning")
    outcome = Column(String(50), default="Pending")

    primary_kpi = Column(String(255))
    target_value = Column(String(100))
    current_value = Column(String(100))
    kpi_target = Column(String(100))
    kpi_actual = Column(String(100))
    dataset_link = Column(String(255))

    start_date = Column(DateTime)
    end_date = Column(DateTime)

    project = relationship("Project", back_populates="experiments")
    assumption = relationship("Assumption", back_populates="experiments")


class Assumption(Base):
    __tablename__ = "assumptions"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    title = Column(String(255))
    category = Column(ASSUMPTION_CATEGORY_ENUM, default="Opportunity")
    evidence_link = Column(Text)
    lane = Column(String(50), default="Now")
    horizon = Column(ASSUMPTION_HORIZON_ENUM, nullable=True)
    validation_status = Column(String(50), default="Testing")
    status = Column(ASSUMPTION_STATUS_ENUM, default="Testing")
    evidence_density = Column(Integer, default=0)
    source_type = Column(String(50))
    source_id = Column(String(255))
    source_snippet = Column(Text)
    confidence_score = Column(Integer, default=0)
    test_and_learn_phase = Column(TEST_AND_LEARN_PHASE_ENUM, default="define")
    test_phase = Column(ASSUMPTION_TEST_PHASE_ENUM, nullable=True)
    last_tested_at = Column(DateTime, default=dt.datetime.utcnow)
    owner_id = Column(String(50))
    updated_at = Column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)

    project = relationship("Project", back_populates="assumptions")
    scores = relationship("DecisionScore", back_populates="assumption")
    experiments = relationship("Experiment", back_populates="assumption")
    decisions = relationship("DecisionVote", back_populates="assumption")


class RoadmapPlan(Base):
    __tablename__ = "roadmap_plans"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    pillar = Column(String(50))
    sub_category = Column(String(100))
    plan_now = Column(Text)
    plan_next = Column(Text)
    plan_later = Column(Text)
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        default=dt.datetime.utcnow,
        onupdate=dt.datetime.utcnow,
    )

    project = relationship("Project", back_populates="roadmap_plans")


class DecisionVote(Base):
    """Tracks team votes on assumption impact vs uncertainty."""

    __tablename__ = "decisions"
    id = Column(Integer, primary_key=True, index=True)
    assumption_id = Column(Integer, ForeignKey("assumptions.id"))
    user_id = Column(String(255))
    impact = Column(Integer)
    uncertainty = Column(Integer)
    created_at = Column(DateTime, default=dt.datetime.utcnow)

    assumption = relationship("Assumption", back_populates="decisions")


class DecisionSession(Base):
    """Represents a live voting round in Slack."""

    __tablename__ = "decision_sessions"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    channel_id = Column(String(255))
    status = Column(String(50), default="active")
    created_at = Column(DateTime, default=dt.datetime.utcnow)

    project = relationship("Project", back_populates="decisions")
    scores = relationship("DecisionScore", back_populates="session")


class DecisionScore(Base):
    """Supports Silent Scoring with multi-criteria ratings."""

    __tablename__ = "decision_scores"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("decision_sessions.id"))
    assumption_id = Column(Integer, ForeignKey("assumptions.id"))
    user_id = Column(String(255))

    impact = Column(Integer)
    uncertainty = Column(Integer)
    feasibility = Column(Integer)
    confidence = Column(Integer)
    rationale = Column(Text)

    session = relationship("DecisionSession", back_populates="scores")
    assumption = relationship("Assumption", back_populates="scores")


class UserState(Base):
    __tablename__ = "user_states"

    user_id = Column(String(255), primary_key=True)
    current_project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)


class OAuthState(Base):
    __tablename__ = "oauth_states"

    state = Column(String(255), primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    user_id = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=dt.datetime.utcnow)


class DbService:
    def __init__(self) -> None:
        self._token_cipher = self._init_token_cipher()
        try:
            if os.getenv("EVIDENTLY_RESET_DB_ON_STARTUP", "false").lower() == "true":
                logging.warning("DROPPING ALL DATABASE TABLES based on EVIDENTLY_RESET_DB_ON_STARTUP env var.")
                Base.metadata.drop_all(bind=engine)

            if os.getenv("EVIDENTLY_AUTO_CREATE_DB", "true").lower() == "true":
                Base.metadata.create_all(bind=engine)
                self._log_schema_status()
        except Exception as exc:  # noqa: BLE001
            logging.warning("Unable to initialize database schema: %s", exc, exc_info=True)

    @staticmethod
    def _init_token_cipher() -> Fernet | None:
        key = Config.GOOGLE_TOKEN_ENCRYPTION_KEY
        if not key:
            logging.warning("GOOGLE_TOKEN_ENCRYPTION_KEY is not set; Google tokens will be stored in plaintext.")
            return None
        try:
            return Fernet(key.encode() if isinstance(key, str) else key)
        except Exception as exc:  # noqa: BLE001
            logging.error("Invalid GOOGLE_TOKEN_ENCRYPTION_KEY: %s", exc)
            return None

    def _encrypt_token(self, value: str | None) -> str | None:
        if not value:
            return None
        if not self._token_cipher:
            return value
        token = self._token_cipher.encrypt(value.encode("utf-8")).decode("utf-8")
        return f"enc:{token}"

    def _decrypt_token(self, value: str | None) -> str | None:
        if not value:
            return None
        if not value.startswith("enc:"):
            return value
        if not self._token_cipher:
            logging.warning("Encrypted token found but GOOGLE_TOKEN_ENCRYPTION_KEY is missing.")
            return None
        token = value[4:]
        try:
            return self._token_cipher.decrypt(token.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            logging.warning("Failed to decrypt Google token with current key.")
            return None

    def _log_schema_status(self) -> None:
        inspector = inspect(engine)
        expected_tables = {
            "projects": {
                "stage",
                "flow_stage",
                "integrations",
                "channel_id",
                "mission",
                "context_summary",
                "google_access_token",
                "google_refresh_token",
                "token_expiry",
                "dashboard_message_ts",
            },
            "assumptions": {
                "validation_status",
                "status",
                "evidence_density",
                "source_type",
                "source_id",
                "confidence_score",
                "test_and_learn_phase",
                "test_phase",
                "last_tested_at",
                "owner_id",
                "updated_at",
                "category",
                "evidence_link",
                "horizon",
            },
            "canvas_items": {"section", "text", "ai_generated"},
            "experiments": {"outcome", "assumption_id", "kpi_target", "kpi_actual"},
            "decisions": {"assumption_id", "impact", "uncertainty", "user_id"},
            "roadmap_plans": {"pillar", "sub_category", "plan_now", "plan_next", "plan_later", "updated_at"},
        }
        missing = []
        for table, required_cols in expected_tables.items():
            if table not in inspector.get_table_names():
                missing.append(f"{table} (missing table)")
                continue
            existing_cols = {col["name"] for col in inspector.get_columns(table)}
            for col in required_cols:
                if col not in existing_cols:
                    missing.append(f"{table}.{col}")
        if missing:
            logging.warning(
                "Database schema appears outdated. Missing: %s. Run a migration or reset the DB before use.",
                ", ".join(missing),
            )

    def run_manual_patch(self) -> str:
        """
        Manually adds missing columns to ALL tables to prevent crashes.
        Safe to run multiple times (uses IF NOT EXISTS).
        """
        try:
            with engine.connect() as connection:
                with connection.begin():
                    # --- 1. Fix PROJECTS Table ---
                    connection.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS mission TEXT;"))
                    connection.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS channel_id VARCHAR(50);"))
                    connection.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS stage VARCHAR(50) DEFAULT 'Define';"))
                    connection.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS flow_stage VARCHAR(50) DEFAULT 'audit';"))
                    connection.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS integrations JSON DEFAULT '{}';"))
                    connection.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS context_summary TEXT;"))
                    connection.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS google_access_token TEXT;"))
                    connection.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS google_refresh_token TEXT;"))
                    connection.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS token_expiry TIMESTAMP;"))
                    connection.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS dashboard_message_ts VARCHAR(50);"))

                    # --- 2. Fix ASSUMPTIONS Table (The one crashing now) ---
                    connection.execute(text("ALTER TABLE assumptions ADD COLUMN IF NOT EXISTS validation_status VARCHAR(50) DEFAULT 'Testing';"))
                    connection.execute(text("ALTER TABLE assumptions ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'Testing';"))
                    connection.execute(text("ALTER TABLE assumptions ADD COLUMN IF NOT EXISTS evidence_density INTEGER DEFAULT 0;"))
                    connection.execute(text("ALTER TABLE assumptions ADD COLUMN IF NOT EXISTS source_type VARCHAR(50);"))
                    connection.execute(text("ALTER TABLE assumptions ADD COLUMN IF NOT EXISTS source_id VARCHAR(255);"))
                    connection.execute(text("ALTER TABLE assumptions ADD COLUMN IF NOT EXISTS source_snippet TEXT;"))
                    connection.execute(text("ALTER TABLE assumptions ADD COLUMN IF NOT EXISTS confidence_score INTEGER DEFAULT 0;"))
                    connection.execute(text("ALTER TABLE assumptions ADD COLUMN IF NOT EXISTS test_and_learn_phase VARCHAR(50) DEFAULT 'define';"))
                    connection.execute(text("ALTER TABLE assumptions ADD COLUMN IF NOT EXISTS test_phase VARCHAR(50);"))
                    connection.execute(text("ALTER TABLE assumptions ADD COLUMN IF NOT EXISTS last_tested_at TIMESTAMP;"))
                    connection.execute(text("ALTER TABLE assumptions ADD COLUMN IF NOT EXISTS owner_id VARCHAR(50);"))
                    connection.execute(text("ALTER TABLE assumptions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;"))
                    connection.execute(text("ALTER TABLE assumptions ADD COLUMN IF NOT EXISTS category VARCHAR(50) DEFAULT 'Opportunity';"))
                    connection.execute(text("ALTER TABLE assumptions ADD COLUMN IF NOT EXISTS evidence_link TEXT;"))
                    connection.execute(text("ALTER TABLE assumptions ADD COLUMN IF NOT EXISTS horizon VARCHAR(50) DEFAULT 'now';"))

                    # --- 3. Fix EXPERIMENTS Table (Prevent future crashes) ---
                    connection.execute(text("ALTER TABLE experiments ADD COLUMN IF NOT EXISTS hypothesis TEXT;"))
                    connection.execute(text("ALTER TABLE experiments ADD COLUMN IF NOT EXISTS method VARCHAR(100);"))
                    connection.execute(text("ALTER TABLE experiments ADD COLUMN IF NOT EXISTS stage VARCHAR(50);"))
                    connection.execute(text("ALTER TABLE experiments ADD COLUMN IF NOT EXISTS assumption_id INTEGER;"))
                    connection.execute(text("ALTER TABLE experiments ADD COLUMN IF NOT EXISTS primary_kpi VARCHAR(255);"))
                    connection.execute(text("ALTER TABLE experiments ADD COLUMN IF NOT EXISTS target_value VARCHAR(100);"))
                    connection.execute(text("ALTER TABLE experiments ADD COLUMN IF NOT EXISTS current_value VARCHAR(100);"))
                    connection.execute(text("ALTER TABLE experiments ADD COLUMN IF NOT EXISTS kpi_target VARCHAR(100);"))
                    connection.execute(text("ALTER TABLE experiments ADD COLUMN IF NOT EXISTS kpi_actual VARCHAR(100);"))
                    connection.execute(text("ALTER TABLE experiments ADD COLUMN IF NOT EXISTS dataset_link VARCHAR(255);"))
                    connection.execute(text("ALTER TABLE experiments ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'planning';"))
                    connection.execute(text("ALTER TABLE experiments ADD COLUMN IF NOT EXISTS outcome VARCHAR(50) DEFAULT 'Pending';"))
                    connection.execute(text("ALTER TABLE experiments ADD COLUMN IF NOT EXISTS start_date TIMESTAMP;"))
                    connection.execute(text("ALTER TABLE experiments ADD COLUMN IF NOT EXISTS end_date TIMESTAMP;"))

                    # --- 4. Add DECISIONS Table (Voting) ---
                    connection.execute(
                        text(
                            """
                            CREATE TABLE IF NOT EXISTS decisions (
                                id INTEGER PRIMARY KEY,
                                assumption_id INTEGER,
                                user_id VARCHAR(255),
                                impact INTEGER,
                                uncertainty INTEGER,
                                created_at TIMESTAMP
                            );
                            """
                        )
                    )

                    # --- 5. Add ROADMAP_PLANS Table ---
                    connection.execute(
                        text(
                            """
                            CREATE TABLE IF NOT EXISTS roadmap_plans (
                                id INTEGER PRIMARY KEY,
                                project_id INTEGER,
                                pillar VARCHAR(50),
                                sub_category VARCHAR(100),
                                plan_now TEXT,
                                plan_next TEXT,
                                plan_later TEXT,
                                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                            );
                            """
                        )
                    )

            return "✅ Database FULLY patched! (Projects, Assumptions, Experiments)"
        except SQLAlchemyError as exc:
            logging.exception("Manual database patch failed.")
            return f"❌ Patch failed: {exc}"

    def create_project(
        self,
        user_id: str,
        name: str,
        description: str | None = None,
        opportunity: str | None = None,
        capability: str | None = None,
        progress: str | None = None,
        mission: str | None = None,
        stage: str = "Define",
        flow_stage: str = "audit",
        channel_id: str | None = None,
        add_starter_kit: bool = True,
    ) -> Project:
        formatted_description = self._format_project_description(opportunity, capability, progress)
        if description and not formatted_description:
            formatted_description = description
        with SessionLocal() as db:
            project = Project(
                name=name,
                description=formatted_description or "",
                mission=mission,
                stage=stage,
                flow_stage=flow_stage,
                created_by=user_id,
                channel_id=channel_id,
            )
            db.add(project)
            db.commit()
            db.refresh(project)

            member = ProjectMember(project_id=project.id, user_id=user_id, role="owner")
            db.add(member)
            if add_starter_kit:
                assumption = Assumption(
                    project_id=project.id,
                    title="We can reach the target audience through community partners.",
                    lane="Now",
                    horizon="now",
                    validation_status="Testing",
                    status="Testing",
                    evidence_density=1,
                    confidence_score=3,
                    test_and_learn_phase="define",
                )
                experiment = Experiment(
                    project_id=project.id,
                    title="Partner outreach pilot",
                    hypothesis="Local partners can recruit 20 participants within two weeks.",
                    method=ToolkitService.DEFAULT_METHOD_NAME,
                    stage="Develop",
                    status="Planning",
                )
                db.add_all([assumption, experiment])
            db.commit()
            self._set_active_project(db, user_id, project.id)
            db.refresh(project)
            return project

    def get_project_by_user(self, user_id: str) -> Optional[Project]:
        with SessionLocal() as db:
            return db.query(Project).filter(Project.created_by == user_id).first()

    def get_project_by_channel(self, channel_id: str) -> Optional[Dict[str, Any]]:
        with SessionLocal() as db:
            project = db.query(Project).filter(Project.channel_id == channel_id).first()
            return self._serialize_project(project) if project else None

    def get_projects_with_dashboard_message_ts(self) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            projects = (
                db.query(Project)
                .filter(Project.dashboard_message_ts.isnot(None))
                .filter(Project.dashboard_message_ts != "")
                .all()
            )
            return [self._serialize_project(project) for project in projects]

    def get_project(self, project_id: int) -> Optional[Dict[str, Any]]:
        with SessionLocal() as db:
            project = (
                db.query(Project)
                .options(
                    joinedload(Project.assumptions),
                    joinedload(Project.experiments),
                    joinedload(Project.members),
                    joinedload(Project.canvas_items),
                    joinedload(Project.roadmap_plans),
                )
                .filter(Project.id == project_id)
                .first()
            )
            return self._serialize_project(project) if project else None

    def get_active_projects(self) -> list[Dict[str, Any]]:
        with SessionLocal() as db:
            projects = (
                db.query(Project)
                .options(
                    joinedload(Project.assumptions),
                    joinedload(Project.experiments),
                    joinedload(Project.members),
                    joinedload(Project.canvas_items),
                    joinedload(Project.roadmap_plans),
                )
                .filter(Project.status == "active")
                .all()
            )
            return [self._serialize_project(project) for project in projects]

    def get_all_projects_with_counts(self) -> list[Dict[str, Any]]:
        with SessionLocal() as db:
            results = (
                db.query(
                    Project.id,
                    Project.name,
                    Project.status,
                    func.count(ProjectMember.id).label("member_count"),
                )
                .outerjoin(Project.members)
                .group_by(Project.id, Project.name, Project.status)
                .all()
            )
            return [
                {
                    "id": result.id,
                    "name": result.name,
                    "status": result.status,
                    "member_count": result.member_count,
                }
                for result in results
            ]

    def delete_empty_projects(self) -> int:
        with SessionLocal() as db:
            subquery = db.query(ProjectMember.project_id).distinct().subquery()
            empty_projects_query = db.query(Project).filter(~Project.id.in_(subquery))
            deleted_count = empty_projects_query.count()
            if deleted_count:
                empty_projects_query.delete(synchronize_session=False)
                db.commit()
            return deleted_count

    def update_project_context(self, project_id: int, context_summary: str) -> None:
        with SessionLocal() as db:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                return
            project.context_summary = context_summary
            db.commit()

    def update_project_details(self, project_id: int, name: str, description: str, mission: str) -> None:
        with SessionLocal() as db:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                return
            project.name = name
            project.description = description
            project.mission = mission
            db.commit()

    def update_project(self, project_id: int, data: dict[str, Any]) -> None:
        allowed_fields = {
            "name",
            "description",
            "mission",
            "stage",
            "flow_stage",
            "channel_id",
            "status",
            "context_summary",
            "integrations",
        }
        with SessionLocal() as db:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                return
            for key, value in data.items():
                if key in allowed_fields:
                    setattr(project, key, value)
            db.commit()

    def archive_project(self, project_id: int) -> None:
        with SessionLocal() as db:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                return
            project.status = "archived"
            db.commit()

    def delete_project(self, project_id: int) -> None:
        with SessionLocal() as db:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                return
            db.delete(project)
            db.commit()

    def leave_project(self, project_id: int, user_id: str) -> None:
        with SessionLocal() as db:
            membership = (
                db.query(ProjectMember)
                .filter(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
                .first()
            )
            if not membership:
                return
            db.delete(membership)
            db.commit()

    def clear_active_project(self, user_id: str) -> None:
        with SessionLocal() as db:
            state = db.query(UserState).filter(UserState.user_id == user_id).first()
            if not state:
                return
            state.current_project_id = None
            db.commit()

    def get_active_project(self, user_id: str) -> Optional[Dict[str, Any]]:
        with SessionLocal() as db:
            state = db.query(UserState).filter(UserState.user_id == user_id).first()
            if state and state.current_project_id:
                project_id = state.current_project_id
            else:
                membership = db.query(ProjectMember).filter(ProjectMember.user_id == user_id).first()
                if not membership or not membership.project:
                    return None
                project_id = membership.project_id
                self._set_active_project(db, user_id, project_id)

            project = (
                db.query(Project)
                .options(
                    joinedload(Project.assumptions),
                    joinedload(Project.experiments),
                    joinedload(Project.members),
                    joinedload(Project.canvas_items),
                )
                .filter(Project.id == project_id)
                .first()
            )
            return self._serialize_project(project) if project else None

    def set_active_project(self, user_id: str, project_id: int) -> None:
        with SessionLocal() as db:
            self._set_active_project(db, user_id, project_id)
            db.commit()

    def create_oauth_state(self, user_id: str, project_id: int) -> str:
        state = secrets.token_urlsafe(32)
        with SessionLocal() as db:
            oauth_state = OAuthState(state=state, project_id=project_id, user_id=user_id)
            db.add(oauth_state)
            db.commit()
        return state

    def consume_oauth_state(self, state: str) -> dict[str, Any] | None:
        with SessionLocal() as db:
            record = db.query(OAuthState).filter(OAuthState.state == state).first()
            if not record:
                return None
            ttl_seconds = Config.OAUTH_STATE_TTL_SECONDS
            if ttl_seconds and record.created_at:
                expires_at = record.created_at + dt.timedelta(seconds=ttl_seconds)
                if dt.datetime.utcnow() > expires_at:
                    db.delete(record)
                    db.commit()
                    return None
            payload = {"project_id": record.project_id, "user_id": record.user_id}
            db.delete(record)
            db.commit()
            return payload

    def get_user_projects(self, user_id: str) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            memberships = (
                db.query(ProjectMember)
                .options(joinedload(ProjectMember.project))
                .filter(ProjectMember.user_id == user_id)
                .all()
            )
            projects = []
            for membership in memberships:
                project = membership.project
                if not project or project.status != "active":
                    continue
                projects.append(
                    {
                        "mission": project.mission,
                        "stage": project.stage,
                        "name": project.name,
                        "id": membership.project_id,
                        "channel_id": project.channel_id,
                        "role": membership.role,
                    }
                )
            return projects

    def remove_project_member(self, project_id: int, user_id: str) -> None:
        with SessionLocal() as db:
            membership = (
                db.query(ProjectMember)
                .filter(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
                .first()
            )
            if not membership:
                return
            db.delete(membership)
            db.commit()

    def count_project_members(self, project_id: int) -> int:
        with SessionLocal() as db:
            return db.query(ProjectMember).filter(ProjectMember.project_id == project_id).count()

    def find_project_by_fuzzy_name(self, name: str) -> int | None:
        """Find project by partial name match.

        Note: ILIKE with a leading wildcard can be slow on large tables. Consider
        a trigram index or full-text search if project count grows.
        """
        if not name:
            return None
        with SessionLocal() as db:
            project = (
                db.query(Project)
                .filter(Project.name.ilike(f"%{name}%"))
                .order_by(Project.id.asc())
                .first()
            )
            return project.id if project else None

    def add_project_member(self, project_id: int, user_id: str, role: str = "member") -> bool:
        with SessionLocal() as db:
            existing = (
                db.query(ProjectMember)
                .filter(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
                .first()
            )
            if existing:
                return False
            member = ProjectMember(project_id=project_id, user_id=user_id, role=role)
            db.add(member)
            db.commit()
            return True

    def set_project_channel(self, project_id: int, channel_id: str) -> None:
        with SessionLocal() as db:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                return
            project.channel_id = channel_id
            db.commit()

    def add_integration_link(self, project_id: int, type_: str, external_id: str | None) -> None:
        with SessionLocal() as db:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                return
            integrations = dict(project.integrations or {})
            if type_ == "drive":
                integrations["drive"] = {"connected": bool(external_id), "folder_id": external_id}
            if type_ == "asana":
                integrations["asana"] = {"connected": bool(external_id), "project_id": external_id}
            if type_ == "miro":
                integrations["miro"] = {"connected": bool(external_id), "board_url": external_id}
            project.integrations = integrations
            db.commit()

    def update_project_integrations(self, project_id: int, integrations: dict[str, Any]) -> None:
        with SessionLocal() as db:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                return
            project.integrations = integrations
            db.commit()

    def set_project_stage(self, project_id: int, stage: str) -> None:
        with SessionLocal() as db:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                return
            project.stage = stage
            db.commit()

    def update_google_tokens(
        self,
        project_id: int,
        access_token: str,
        refresh_token: str | None,
        expires_in: int | None,
    ) -> None:
        with SessionLocal() as db:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                return
            project.google_access_token = self._encrypt_token(access_token)
            if refresh_token:
                project.google_refresh_token = self._encrypt_token(refresh_token)
            if expires_in:
                project.token_expiry = dt.datetime.utcnow() + dt.timedelta(seconds=expires_in)
            db.commit()

    def get_google_token(self, project_id: int) -> dict[str, Any] | None:
        with SessionLocal() as db:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                return None
            return {
                "access_token": self._decrypt_token(project.google_access_token),
                "refresh_token": self._decrypt_token(project.google_refresh_token),
                "token_expiry": project.token_expiry,
            }

    def add_canvas_item(self, project_id: int, section: str, text: str, is_ai: bool = False) -> None:
        with SessionLocal() as db:
            item = CanvasItem(
                project_id=project_id,
                section=section,
                text=text,
                ai_generated=is_ai,
            )
            db.add(item)
            db.commit()

    def get_metrics(self, project_id: int) -> Dict[str, int]:
        with SessionLocal() as db:
            total_exp = db.query(Experiment).filter_by(project_id=project_id).count()
            validated = (
                db.query(Assumption)
                .filter_by(project_id=project_id, validation_status="Validated")
                .count()
            )
            rejected = (
                db.query(Assumption)
                .filter_by(project_id=project_id, validation_status="Rejected")
                .count()
            )
            return {"experiments": total_exp, "validated": validated, "rejected": rejected}

    def create_collection(self, project_id: int, name: str, description: str | None) -> Collection:
        with SessionLocal() as db:
            collection = Collection(project_id=project_id, name=name, description=description)
            db.add(collection)
            db.commit()
            db.refresh(collection)
            return collection

    def get_collections(self, project_id: int) -> list[dict]:
        with SessionLocal() as db:
            collections = db.query(Collection).filter(Collection.project_id == project_id).all()
            return [self._serialize_collection(item) for item in collections]

    def create_automation_rule(self, project_id: int, trigger: str, action: str) -> AutomationRule:
        with SessionLocal() as db:
            rule = AutomationRule(project_id=project_id, trigger_event=trigger, action_type=action)
            db.add(rule)
            db.commit()
            db.refresh(rule)
            return rule

    def get_automation_rules(self, project_id: int) -> list[dict]:
        with SessionLocal() as db:
            rules = db.query(AutomationRule).filter(AutomationRule.project_id == project_id).all()
            return [self._serialize_automation_rule(item) for item in rules]

    def get_experiments(self, project_id: int) -> list[dict]:
        with SessionLocal() as db:
            experiments = db.query(Experiment).filter_by(project_id=project_id).all()
            return [self._serialize_experiment(exp) for exp in experiments]

    def get_recent_experiment_outcomes(self, days: int = 7) -> list[Dict[str, Any]]:
        cutoff = dt.datetime.utcnow() - dt.timedelta(days=days)
        with SessionLocal() as db:
            experiments = (
                db.query(Experiment)
                .options(joinedload(Experiment.project))
                .filter(Experiment.outcome.in_(["Validated", "Invalidated"]))
                .filter(
                    or_(
                        Experiment.end_date.isnot(None) & (Experiment.end_date >= cutoff),
                        Experiment.start_date.isnot(None) & (Experiment.start_date >= cutoff),
                    )
                )
                .all()
            )
            results: list[Dict[str, Any]] = []
            for experiment in experiments:
                project = experiment.project
                results.append(
                    {
                        "project_name": project.name if project else "Project",
                        "hypothesis": experiment.hypothesis or experiment.title or "a hypothesis",
                        "outcome": experiment.outcome,
                    }
                )
            return results

    def get_stale_projects(self, days: int = 14) -> list[Dict[str, Any]]:
        cutoff = dt.datetime.utcnow() - dt.timedelta(days=days)
        with SessionLocal() as db:
            latest_assumption = (
                db.query(
                    Assumption.project_id.label("project_id"),
                    func.max(Assumption.updated_at).label("latest_assumption"),
                )
                .group_by(Assumption.project_id)
                .subquery()
            )
            latest_experiment = (
                db.query(
                    Experiment.project_id.label("project_id"),
                    func.max(func.coalesce(Experiment.end_date, Experiment.start_date)).label("latest_experiment"),
                )
                .group_by(Experiment.project_id)
                .subquery()
            )
            last_activity = func.max(
                func.coalesce(latest_assumption.c.latest_assumption, Project.created_at),
                func.coalesce(latest_experiment.c.latest_experiment, Project.created_at),
                Project.created_at,
            )
            projects = (
                db.query(Project)
                .outerjoin(latest_assumption, latest_assumption.c.project_id == Project.id)
                .outerjoin(latest_experiment, latest_experiment.c.project_id == Project.id)
                .filter(Project.status == "active")
                .filter(last_activity < cutoff)
                .all()
            )
            return [
                {
                    "id": project.id,
                    "name": project.name,
                    "created_by": project.created_by,
                }
                for project in projects
            ]

    def create_experiment(
        self,
        project_id: int,
        title: str | None = None,
        method: str | None = None,
        hypothesis: str | None = None,
        assumption_id: int | None = None,
        data: dict | None = None,
    ) -> Experiment:
        data = data or {}
        if title is not None:
            data["title"] = title
        if method is not None:
            data["method"] = method
        if hypothesis is not None:
            data["hypothesis"] = hypothesis
        if assumption_id is not None:
            data["assumption_id"] = assumption_id
        data.setdefault("stage", "Develop")
        data.setdefault("status", "Planning")
        data.setdefault("outcome", "Pending")
        with SessionLocal() as db:
            experiment = Experiment(
                project_id=project_id,
                assumption_id=data.get("assumption_id"),
                title=data.get("title"),
                hypothesis=data.get("hypothesis"),
                method=data.get("method"),
                stage=data.get("stage"),
                status=data.get("status", "Planning"),
                outcome=data.get("outcome", "Pending"),
                primary_kpi=data.get("primary_kpi"),
                target_value=data.get("target_value"),
                current_value=data.get("current_value"),
                kpi_target=data.get("kpi_target", data.get("target_value")),
                kpi_actual=data.get("kpi_actual", data.get("current_value")),
                dataset_link=data.get("dataset_link"),
            )
            db.add(experiment)
            db.commit()
            db.refresh(experiment)
            return experiment

    def update_experiment(
        self,
        experiment_id: int,
        data: dict | None = None,
        status: str | None = None,
        kpi: str | None = None,
    ) -> None:
        data = data or {}
        if status is not None:
            data["status"] = status
        if kpi is not None:
            data["current_value"] = kpi
        with SessionLocal() as db:
            experiment = db.query(Experiment).filter(Experiment.id == experiment_id).first()
            if not experiment:
                return
            if "title" in data:
                experiment.title = data["title"]
            if "hypothesis" in data:
                experiment.hypothesis = data["hypothesis"]
            if "method" in data:
                experiment.method = data["method"]
            if "stage" in data:
                experiment.stage = data["stage"]
            if "status" in data:
                experiment.status = data["status"]
            if "outcome" in data:
                experiment.outcome = data["outcome"]
                if experiment.end_date is None and data["outcome"] in {"Validated", "Invalidated"}:
                    experiment.end_date = dt.datetime.utcnow()
            if "assumption_id" in data:
                experiment.assumption_id = data["assumption_id"]
            if "primary_kpi" in data:
                experiment.primary_kpi = data["primary_kpi"]
            if "target_value" in data:
                experiment.target_value = data["target_value"]
            if "current_value" in data:
                experiment.current_value = data["current_value"]
            if "kpi_target" in data:
                experiment.kpi_target = data["kpi_target"]
            if "kpi_actual" in data:
                experiment.kpi_actual = data["kpi_actual"]
            if "dataset_link" in data:
                experiment.dataset_link = data["dataset_link"]
            db.commit()

    def create_assumption(self, project_id: int, data: dict) -> Assumption:
        with SessionLocal() as db:
            lane_value = data.get("lane", "Now")
            horizon_value = data.get("horizon") or lane_value.lower()
            test_phase = data.get("test_phase") or data.get("test_and_learn_phase")
            assumption = Assumption(
                project_id=project_id,
                title=data.get("title"),
                category=data.get("category", "Opportunity"),
                evidence_link=data.get("evidence_link"),
                lane=lane_value,
                validation_status=data.get("validation_status", "Testing"),
                status=data.get("status", data.get("validation_status", "Testing")),
                evidence_density=data.get("evidence_density", 0),
                source_type=data.get("source_type"),
                source_id=data.get("source_id"),
                source_snippet=data.get("source_snippet"),
                confidence_score=data.get("confidence_score", 0),
                horizon=horizon_value if horizon_value in {"now", "next", "later"} else "now",
                test_and_learn_phase=data.get("test_and_learn_phase", "define"),
                test_phase=test_phase,
                last_tested_at=data.get("last_tested_at", dt.datetime.utcnow()),
                owner_id=data.get("owner_id"),
            )
            db.add(assumption)
            db.commit()
            db.refresh(assumption)
            return assumption

    def find_similar_assumption(
        self,
        project_id: int,
        title: str,
        threshold: float = 0.9,
    ) -> Optional[str]:
        """Return a similar assumption title if similarity exceeds threshold."""
        if not title:
            return None
        words = set(title.lower().split())
        if not words:
            return None
        with SessionLocal() as db:
            assumptions = db.query(Assumption).filter(Assumption.project_id == project_id).all()
            for assumption in assumptions:
                existing = (assumption.title or "").lower().split()
                if not existing:
                    continue
                overlap = words.intersection(existing)
                score = len(overlap) / max(len(words), len(existing))
                if score >= threshold:
                    return assumption.title
        return None

    def update_assumption_lane(self, assumption_id: int, lane: str) -> None:
        with SessionLocal() as db:
            assumption = db.query(Assumption).filter(Assumption.id == assumption_id).first()
            if not assumption:
                return
            assumption.lane = lane
            db.commit()

    def update_assumption_validation_status(self, assumption_id: int, status: str) -> None:
        with SessionLocal() as db:
            assumption = db.query(Assumption).filter(Assumption.id == assumption_id).first()
            if not assumption:
                return
            assumption.validation_status = status
            assumption.status = status
            assumption.last_tested_at = dt.datetime.utcnow()
            db.commit()

    def touch_assumption(self, assumption_id: int) -> None:
        with SessionLocal() as db:
            assumption = db.query(Assumption).filter(Assumption.id == assumption_id).first()
            if not assumption:
                return
            assumption.updated_at = dt.datetime.utcnow()
            assumption.last_tested_at = dt.datetime.utcnow()
            db.commit()

    def update_assumption(self, assumption_id: int, data: dict) -> None:
        with SessionLocal() as db:
            assumption = db.query(Assumption).filter(Assumption.id == assumption_id).first()
            if not assumption:
                return
            if "title" in data:
                assumption.title = data["title"]
            if "lane" in data:
                assumption.lane = data["lane"]
            if "validation_status" in data:
                assumption.validation_status = data["validation_status"]
                assumption.status = data["validation_status"]
                assumption.last_tested_at = dt.datetime.utcnow()
            if "status" in data:
                assumption.status = data["status"]
                assumption.validation_status = data["status"]
                assumption.last_tested_at = dt.datetime.utcnow()
            if "evidence_density" in data:
                assumption.evidence_density = data["evidence_density"]
            if "category" in data:
                assumption.category = data["category"]
            if "evidence_link" in data:
                assumption.evidence_link = data["evidence_link"]
            if "confidence_score" in data:
                assumption.confidence_score = data["confidence_score"]
            if "horizon" in data:
                assumption.horizon = data["horizon"]
            if "test_and_learn_phase" in data:
                assumption.test_and_learn_phase = data["test_and_learn_phase"]
            if "test_phase" in data:
                assumption.test_phase = data["test_phase"]
            if "owner_id" in data:
                assumption.owner_id = data["owner_id"]
            db.commit()

    def update_project_flow_stage(self, project_id: int, flow_stage: str) -> None:
        with SessionLocal() as db:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                return
            project.flow_stage = flow_stage
            db.commit()

    def update_assumption_confidence_score(self, assumption_id: int, confidence_score: int) -> None:
        self.update_assumption(assumption_id, {"confidence_score": confidence_score})

    def update_assumption_horizon(self, assumption_id: int, horizon: str) -> None:
        self.update_assumption(assumption_id, {"horizon": horizon})

    def update_assumption_test_and_learn_phase(self, assumption_id: int, phase: str) -> None:
        self.update_assumption(assumption_id, {"test_and_learn_phase": phase})

    def upsert_diagnostic_assumption(
        self,
        project_id: int,
        category: str,
        question: str,
        confidence_score: int,
        answer: str | None = None,
    ) -> Assumption:
        with SessionLocal() as db:
            assumption = (
                db.query(Assumption)
                .filter(
                    Assumption.project_id == project_id,
                    Assumption.title == question,
                    Assumption.category == category,
                )
                .first()
            )
            if not assumption:
                assumption = Assumption(
                    project_id=project_id,
                    title=question,
                    category=category,
                    validation_status="Testing",
                    status="Testing",
                    confidence_score=confidence_score,
                    horizon="now",
                    test_and_learn_phase="define",
                    source_snippet=answer or None,
                )
                db.add(assumption)
            else:
                assumption.confidence_score = confidence_score
                if answer is not None:
                    assumption.source_snippet = answer
            db.commit()
            db.refresh(assumption)
            return assumption

    def get_roadmap_plan(self, project_id: int, pillar: str, sub_category: str) -> Optional[Dict[str, Any]]:
        with SessionLocal() as db:
            plan = (
                db.query(RoadmapPlan)
                .filter(
                    RoadmapPlan.project_id == project_id,
                    RoadmapPlan.pillar == pillar,
                    RoadmapPlan.sub_category == sub_category,
                )
                .first()
            )
            return self._serialize_roadmap_plan(plan) if plan else None

    def upsert_roadmap_plan(
        self,
        project_id: int,
        pillar: str,
        sub_category: str,
        plan_now: str | None,
        plan_next: str | None,
        plan_later: str | None,
    ) -> RoadmapPlan:
        with SessionLocal() as db:
            plan = (
                db.query(RoadmapPlan)
                .filter(
                    RoadmapPlan.project_id == project_id,
                    RoadmapPlan.pillar == pillar,
                    RoadmapPlan.sub_category == sub_category,
                )
                .first()
            )
            if not plan:
                plan = RoadmapPlan(
                    project_id=project_id,
                    pillar=pillar,
                    sub_category=sub_category,
                    plan_now=plan_now,
                    plan_next=plan_next,
                    plan_later=plan_later,
                )
                db.add(plan)
            else:
                plan.plan_now = plan_now
                plan.plan_next = plan_next
                plan.plan_later = plan_later
            db.commit()
            db.refresh(plan)
            return plan

    def update_assumption_title(self, assumption_id: int, new_title: str) -> None:
        self.update_assumption(assumption_id, {"title": new_title})

    def update_assumption_text(self, assumption_id: int, new_text: str) -> None:
        self.update_assumption(assumption_id, {"title": new_text})

    def delete_assumption(self, assumption_id: int) -> None:
        with SessionLocal() as db:
            assumption = db.query(Assumption).filter(Assumption.id == assumption_id).first()
            if not assumption:
                return
            db.delete(assumption)
            db.commit()

    def delete_experiment(self, experiment_id: int) -> None:
        with SessionLocal() as db:
            experiment = db.query(Experiment).filter(Experiment.id == experiment_id).first()
            if not experiment:
                return
            db.delete(experiment)
            db.commit()

    def get_experiment(self, experiment_id: int) -> Optional[Dict[str, Any]]:
        with SessionLocal() as db:
            experiment = db.query(Experiment).filter(Experiment.id == experiment_id).first()
            return self._serialize_experiment(experiment) if experiment else None

    def get_experiment_by_asana_task_id(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Fetch an experiment linked to an Asana task."""
        with SessionLocal() as db:
            experiment = db.query(Experiment).filter(Experiment.dataset_link == f"asana:{task_id}").first()
            return self._serialize_experiment(experiment) if experiment else None

    def get_assumption(self, assumption_id: int) -> Optional[Dict[str, Any]]:
        with SessionLocal() as db:
            assumption = db.query(Assumption).filter(Assumption.id == assumption_id).first()
            return self._serialize_assumption(assumption) if assumption else None

    def get_stale_assumptions(self, days_threshold: int = 14) -> list[Dict[str, Any]]:
        cutoff = dt.datetime.utcnow() - dt.timedelta(days=days_threshold)
        with SessionLocal() as db:
            assumptions = (
                db.query(Assumption)
                .options(joinedload(Assumption.project))
                .filter(
                    Assumption.status == "Testing",
                )
                .all()
            )
            results = []
            for assumption in assumptions:
                project = assumption.project
                results.append(
                    {
                        "assumption": self._serialize_assumption(assumption),
                        "project": {
                            "id": project.id,
                            "name": project.name,
                            "channel_id": project.channel_id,
                            "created_by": project.created_by,
                        },
                    }
                )
            return results

    def create_decision_session(self, project_id: int, channel_id: str) -> int:
        with SessionLocal() as db:
            session = DecisionSession(project_id=project_id, channel_id=channel_id)
            db.add(session)
            db.commit()
            db.refresh(session)
            return session.id

    def record_decision_score(
        self,
        session_id: int,
        assumption_id: int,
        user_id: str,
        impact: int,
        uncertainty: int,
        feasibility: int,
        confidence: int,
        rationale: str | None = None,
    ) -> None:
        with SessionLocal() as db:
            score = (
                db.query(DecisionScore)
                .filter_by(session_id=session_id, assumption_id=assumption_id, user_id=user_id)
                .first()
            )

            if not score:
                score = DecisionScore(session_id=session_id, assumption_id=assumption_id, user_id=user_id)
                db.add(score)

            score.impact = impact
            score.uncertainty = uncertainty
            score.feasibility = feasibility
            score.confidence = confidence
            score.rationale = rationale
            db.commit()

    def get_session_scores(self, session_id: int) -> Dict[int, list[DecisionScore]]:
        with SessionLocal() as db:
            scores = db.query(DecisionScore).filter(DecisionScore.session_id == session_id).all()
            results: Dict[int, list[DecisionScore]] = defaultdict(list)
            for score in scores:
                results[score.assumption_id].append(score)
            return dict(results)

    def record_decision_vote(
        self,
        assumption_id: int,
        user_id: str,
        impact: int,
        uncertainty: int,
    ) -> None:
        with SessionLocal() as db:
            vote = (
                db.query(DecisionVote)
                .filter_by(assumption_id=assumption_id, user_id=user_id)
                .first()
            )
            if not vote:
                vote = DecisionVote(assumption_id=assumption_id, user_id=user_id)
                db.add(vote)
            vote.impact = impact
            vote.uncertainty = uncertainty
            db.commit()

    def get_decision_vote_summary(self, assumption_id: int) -> Dict[str, float]:
        with SessionLocal() as db:
            votes = db.query(DecisionVote).filter(DecisionVote.assumption_id == assumption_id).all()
            if not votes:
                return {"count": 0, "avg_impact": 0.0, "avg_uncertainty": 0.0}
            total_impact = sum(vote.impact or 0 for vote in votes)
            total_uncertainty = sum(vote.uncertainty or 0 for vote in votes)
            count = len(votes)
            return {
                "count": count,
                "avg_impact": round(total_impact / count, 2),
                "avg_uncertainty": round(total_uncertainty / count, 2),
            }

    def _set_active_project(self, db: Session, user_id: str, project_id: int) -> None:
        state = db.query(UserState).filter(UserState.user_id == user_id).first()
        if not state:
            state = UserState(user_id=user_id)
            db.add(state)
        state.current_project_id = project_id

    def _serialize_project(self, project: Project) -> Dict[str, Any]:
        return {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "mission": project.mission,
            "context_summary": project.context_summary,
            "status": project.status,
            "stage": project.stage,
            "flow_stage": project.flow_stage,
            "channel_id": project.channel_id,
            "created_by": project.created_by,
            "dashboard_message_ts": project.dashboard_message_ts,
            "integrations": project.integrations,
            "assumptions": [self._serialize_assumption(a) for a in project.assumptions],
            "experiments": [self._serialize_experiment(exp) for exp in project.experiments],
            "members": [{"user_id": member.user_id, "role": member.role} for member in project.members],
            "collections": [self._serialize_collection(item) for item in project.collections],
            "automation_rules": [self._serialize_automation_rule(item) for item in project.automation_rules],
            "roadmap_plans": [self._serialize_roadmap_plan(item) for item in project.roadmap_plans],
            "canvas_items": [
                {
                    "id": item.id,
                    "section": item.section,
                    "text": item.text,
                    "ai_generated": item.ai_generated,
                }
                for item in project.canvas_items
            ],
        }

    def _serialize_collection(self, collection: Collection) -> Dict[str, Any]:
        return {
            "id": collection.id,
            "name": collection.name,
            "description": collection.description,
        }

    def _serialize_roadmap_plan(self, plan: RoadmapPlan) -> Dict[str, Any]:
        return {
            "id": plan.id,
            "project_id": plan.project_id,
            "pillar": plan.pillar,
            "sub_category": plan.sub_category,
            "plan_now": plan.plan_now,
            "plan_next": plan.plan_next,
            "plan_later": plan.plan_later,
            "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
        }

    def _serialize_automation_rule(self, rule: AutomationRule) -> Dict[str, Any]:
        return {
            "id": rule.id,
            "trigger_event": rule.trigger_event,
            "action_type": rule.action_type,
            "is_active": rule.is_active,
        }

    def _serialize_experiment(self, experiment: Experiment) -> Dict[str, Any]:
        return {
            "id": experiment.id,
            "project_id": experiment.project_id,
            "assumption_id": experiment.assumption_id,
            "title": experiment.title,
            "hypothesis": experiment.hypothesis,
            "method": experiment.method,
            "stage": experiment.stage,
            "status": experiment.status,
            "outcome": experiment.outcome,
            "primary_kpi": experiment.primary_kpi,
            "target_value": experiment.target_value,
            "current_value": experiment.current_value,
            "kpi_target": experiment.kpi_target,
            "kpi_actual": experiment.kpi_actual,
            "dataset_link": experiment.dataset_link,
        }

    def _serialize_assumption(self, assumption: Assumption) -> Dict[str, Any]:
        return {
            "id": assumption.id,
            "title": assumption.title,
            "category": assumption.category,
            "evidence_link": assumption.evidence_link,
            "lane": assumption.lane,
            "horizon": assumption.horizon,
            "validation_status": assumption.validation_status,
            "status": assumption.status,
            "evidence_density": assumption.evidence_density,
            "source_type": assumption.source_type,
            "source_id": assumption.source_id,
            "source_snippet": assumption.source_snippet,
            "confidence_score": assumption.confidence_score,
            "test_and_learn_phase": assumption.test_and_learn_phase,
            "test_phase": assumption.test_phase,
            "last_tested_at": assumption.last_tested_at.isoformat() if assumption.last_tested_at else None,
            "owner_id": assumption.owner_id,
            "updated_at": assumption.updated_at.isoformat() if assumption.updated_at else None,
        }

    @staticmethod
    def _format_project_description(
        opportunity: str | None,
        capability: str | None,
        progress: str | None,
    ) -> str:
        sections = []
        if opportunity:
            sections.append(f"Opportunity:\n{opportunity}")
        if capability:
            sections.append(f"Capability:\n{capability}")
        if progress:
            sections.append(f"Progress:\n{progress}")
        return "\n\n".join(sections)
