import datetime as dt
import logging
import os
from collections import defaultdict
from typing import Any, Dict, Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, create_engine, inspect, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, declarative_base, joinedload, relationship, sessionmaker

from services.toolkit_service import ToolkitService

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./evidently.db")


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
    channel_id = Column(String(50))
    created_by = Column(String(50))
    created_at = Column(DateTime, default=dt.datetime.utcnow)

    integrations = Column(
        JSON,
        default=lambda: {
            "drive": {"connected": False, "folder_id": None},
            "calendar": {"connected": False},
            "asana": {"connected": False, "project_id": None},
        },
    )

    canvas_items = relationship("CanvasItem", back_populates="project", cascade="all, delete-orphan")
    experiments = relationship("Experiment", back_populates="project", cascade="all, delete-orphan")
    assumptions = relationship("Assumption", back_populates="project", cascade="all, delete-orphan")
    members = relationship("ProjectMember", back_populates="project", cascade="all, delete-orphan")
    decisions = relationship("DecisionSession", back_populates="project")
    collections = relationship("Collection", back_populates="project", cascade="all, delete-orphan")
    automation_rules = relationship("AutomationRule", back_populates="project", cascade="all, delete-orphan")


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

    title = Column(String(255))
    hypothesis = Column(Text)
    method = Column(String(100))
    stage = Column(String(50))
    status = Column(String(50), default="planning")

    primary_kpi = Column(String(255))
    target_value = Column(String(100))
    current_value = Column(String(100))
    dataset_link = Column(String(255))

    project = relationship("Project", back_populates="experiments")


class Assumption(Base):
    __tablename__ = "assumptions"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    title = Column(String(255))
    lane = Column(String(50), default="Now")
    validation_status = Column(String(50), default="Testing")
    evidence_density = Column(Integer, default=0)
    source_type = Column(String(50))
    source_id = Column(String(255))
    source_snippet = Column(Text)
    confidence_score = Column(Integer, default=0)
    updated_at = Column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)

    project = relationship("Project", back_populates="assumptions")
    scores = relationship("DecisionScore", back_populates="assumption")


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


class DbService:
    def __init__(self) -> None:
        try:
            if os.getenv("EVIDENTLY_RESET_DB_ON_STARTUP", "false").lower() == "true":
                logging.warning("DROPPING ALL DATABASE TABLES based on EVIDENTLY_RESET_DB_ON_STARTUP env var.")
                Base.metadata.drop_all(bind=engine)

            if os.getenv("EVIDENTLY_AUTO_CREATE_DB", "true").lower() == "true":
                Base.metadata.create_all(bind=engine)
                self._log_schema_status()
        except Exception as exc:  # noqa: BLE001
            logging.warning("Unable to initialize database schema: %s", exc, exc_info=True)

    def _log_schema_status(self) -> None:
        inspector = inspect(engine)
        expected_tables = {
            "projects": {"stage", "integrations", "channel_id", "mission", "context_summary"},
            "assumptions": {
                "validation_status",
                "evidence_density",
                "source_type",
                "source_id",
                "confidence_score",
                "updated_at",
            },
            "canvas_items": {"section", "text", "ai_generated"},
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
                    connection.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS integrations JSON DEFAULT '{}';"))
                    connection.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS context_summary TEXT;"))

                    # --- 2. Fix ASSUMPTIONS Table (The one crashing now) ---
                    connection.execute(text("ALTER TABLE assumptions ADD COLUMN IF NOT EXISTS validation_status VARCHAR(50) DEFAULT 'Untested';"))
                    connection.execute(text("ALTER TABLE assumptions ADD COLUMN IF NOT EXISTS evidence_density INTEGER DEFAULT 0;"))
                    connection.execute(text("ALTER TABLE assumptions ADD COLUMN IF NOT EXISTS source_type VARCHAR(50);"))
                    connection.execute(text("ALTER TABLE assumptions ADD COLUMN IF NOT EXISTS source_id VARCHAR(100);"))
                    connection.execute(text("ALTER TABLE assumptions ADD COLUMN IF NOT EXISTS source_snippet TEXT;"))
                    connection.execute(text("ALTER TABLE assumptions ADD COLUMN IF NOT EXISTS confidence_score INTEGER DEFAULT 0;"))

                    # --- 3. Fix EXPERIMENTS Table (Prevent future crashes) ---
                    connection.execute(text("ALTER TABLE experiments ADD COLUMN IF NOT EXISTS hypothesis TEXT;"))
                    connection.execute(text("ALTER TABLE experiments ADD COLUMN IF NOT EXISTS kpi VARCHAR(100);"))
                    connection.execute(text("ALTER TABLE experiments ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'Planned';"))
                    connection.execute(text("ALTER TABLE experiments ADD COLUMN IF NOT EXISTS start_date TIMESTAMP;"))
                    connection.execute(text("ALTER TABLE experiments ADD COLUMN IF NOT EXISTS end_date TIMESTAMP;"))

            return "✅ Database FULLY patched! (Projects, Assumptions, Experiments)"
        except SQLAlchemyError as exc:
            logging.exception("Manual database patch failed.")
            return f"❌ Patch failed: {exc}"
            
    def create_project(
        self,
        user_id: str,
        name: str,
        description: str | None = None,
        mission: str | None = None,
        stage: str = "Define",
        channel_id: str | None = None,
        add_starter_kit: bool = True,
    ) -> Project:
        with SessionLocal() as db:
            project = Project(
                name=name,
                description=description or "",
                mission=mission,
                stage=stage,
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
                    validation_status="Testing",
                    evidence_density=1,
                    confidence_score=40,
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

    def get_project(self, project_id: int) -> Optional[Dict[str, Any]]:
        with SessionLocal() as db:
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

    def get_active_projects(self) -> list[Dict[str, Any]]:
        with SessionLocal() as db:
            projects = (
                db.query(Project)
                .options(
                    joinedload(Project.assumptions),
                    joinedload(Project.experiments),
                    joinedload(Project.members),
                    joinedload(Project.canvas_items),
                )
                .filter(Project.status == "active")
                .all()
            )
            return [self._serialize_project(project) for project in projects]

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

    def get_user_projects(self, user_id: str) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            memberships = db.query(ProjectMember).options(joinedload(ProjectMember.project)).filter(
                ProjectMember.user_id == user_id
            ).all()
            return [{"name": m.project.name, "id": m.project_id} for m in memberships if m.project]

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
            project.integrations = integrations
            db.commit()

    def set_project_stage(self, project_id: int, stage: str) -> None:
        with SessionLocal() as db:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                return
            project.stage = stage
            db.commit()

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

    def create_experiment(
        self,
        project_id: int,
        title: str | None = None,
        method: str | None = None,
        hypothesis: str | None = None,
        data: dict | None = None,
    ) -> Experiment:
        data = data or {}
        if title is not None:
            data["title"] = title
        if method is not None:
            data["method"] = method
        if hypothesis is not None:
            data["hypothesis"] = hypothesis
        data.setdefault("stage", "Develop")
        data.setdefault("status", "Planning")
        with SessionLocal() as db:
            experiment = Experiment(
                project_id=project_id,
                title=data.get("title"),
                hypothesis=data.get("hypothesis"),
                method=data.get("method"),
                stage=data.get("stage"),
                status=data.get("status", "Planning"),
                primary_kpi=data.get("primary_kpi"),
                target_value=data.get("target_value"),
                current_value=data.get("current_value"),
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
            if "primary_kpi" in data:
                experiment.primary_kpi = data["primary_kpi"]
            if "target_value" in data:
                experiment.target_value = data["target_value"]
            if "current_value" in data:
                experiment.current_value = data["current_value"]
            if "dataset_link" in data:
                experiment.dataset_link = data["dataset_link"]
            db.commit()

    def create_assumption(self, project_id: int, data: dict) -> Assumption:
        with SessionLocal() as db:
            assumption = Assumption(
                project_id=project_id,
                title=data.get("title"),
                lane=data.get("lane", "Now"),
                validation_status=data.get("validation_status", "Testing"),
                evidence_density=data.get("evidence_density", 0),
                source_type=data.get("source_type"),
                source_id=data.get("source_id"),
                source_snippet=data.get("source_snippet"),
                confidence_score=data.get("confidence_score", 0),
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
            db.commit()

    def touch_assumption(self, assumption_id: int) -> None:
        with SessionLocal() as db:
            assumption = db.query(Assumption).filter(Assumption.id == assumption_id).first()
            if not assumption:
                return
            assumption.updated_at = dt.datetime.utcnow()
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
            if "evidence_density" in data:
                assumption.evidence_density = data["evidence_density"]
            db.commit()

    def update_assumption_title(self, assumption_id: int, new_title: str) -> None:
        self.update_assumption(assumption_id, {"title": new_title})

    def delete_assumption(self, assumption_id: int) -> None:
        with SessionLocal() as db:
            assumption = db.query(Assumption).filter(Assumption.id == assumption_id).first()
            if not assumption:
                return
            db.delete(assumption)
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
                .filter(Assumption.validation_status == "Testing", Assumption.updated_at < cutoff)
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
            "channel_id": project.channel_id,
            "integrations": project.integrations,
            "assumptions": [self._serialize_assumption(a) for a in project.assumptions],
            "experiments": [self._serialize_experiment(exp) for exp in project.experiments],
            "members": [{"user_id": member.user_id, "role": member.role} for member in project.members],
            "collections": [self._serialize_collection(item) for item in project.collections],
            "automation_rules": [self._serialize_automation_rule(item) for item in project.automation_rules],
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
            "title": experiment.title,
            "hypothesis": experiment.hypothesis,
            "method": experiment.method,
            "stage": experiment.stage,
            "status": experiment.status,
            "primary_kpi": experiment.primary_kpi,
            "target_value": experiment.target_value,
            "current_value": experiment.current_value,
            "dataset_link": experiment.dataset_link,
        }

    def _serialize_assumption(self, assumption: Assumption) -> Dict[str, Any]:
        return {
            "id": assumption.id,
            "title": assumption.title,
            "lane": assumption.lane,
            "validation_status": assumption.validation_status,
            "evidence_density": assumption.evidence_density,
            "source_type": assumption.source_type,
            "source_id": assumption.source_id,
            "source_snippet": assumption.source_snippet,
            "confidence_score": assumption.confidence_score,
            "updated_at": assumption.updated_at.isoformat() if assumption.updated_at else None,
        }
