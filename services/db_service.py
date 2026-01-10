import datetime as dt
import logging
from collections import defaultdict
from typing import Any, Dict, Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, create_engine, inspect
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import declarative_base, joinedload, relationship, sessionmaker

from config import Config


def _build_engine():
    url = make_url(Config.DATABASE_URL)
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
            # ⚠️ TEMPORARY: Uncomment once to reset DB for new schema, then comment out.
            # Base.metadata.drop_all(bind=engine)
            Base.metadata.create_all(bind=engine)
            self._log_schema_status()
        except Exception as exc:  # noqa: BLE001
            logging.warning("Unable to initialize database schema: %s", exc, exc_info=True)

    def _log_schema_status(self) -> None:
        inspector = inspect(engine)
        expected_tables = {
            "projects": {"stage", "integrations", "channel_id"},
            "assumptions": {"validation_status", "evidence_density", "source_type", "source_id", "confidence_score"},
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

    def create_project(
        self,
        user_id: str,
        name: str,
        description: str | None = None,
        stage: str = "Define",
        channel_id: str | None = None,
    ) -> Project:
        with SessionLocal() as db:
            project = Project(
                name=name,
                description=description or "",
                stage=stage,
                created_by=user_id,
                channel_id=channel_id,
            )
            db.add(project)
            db.commit()
            db.refresh(project)

            member = ProjectMember(project_id=project.id, user_id=user_id, role="owner")
            db.add(member)
            db.commit()
            self._set_active_project(db, user_id, project.id)
            db.refresh(project)
            return project

    def get_project_by_user(self, user_id: str) -> Optional[Project]:
        with SessionLocal() as db:
            return db.query(Project).filter(Project.created_by == user_id).first()

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

    def get_user_projects(self, user_id: str) -> list[dict]:
        with SessionLocal() as db:
            memberships = db.query(ProjectMember).options(joinedload(ProjectMember.project)).filter(
                ProjectMember.user_id == user_id
            ).all()
            return [{"name": m.project.name, "id": m.project_id} for m in memberships if m.project]

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

    def get_assumption(self, assumption_id: int) -> Optional[Dict[str, Any]]:
        with SessionLocal() as db:
            assumption = db.query(Assumption).filter(Assumption.id == assumption_id).first()
            return self._serialize_assumption(assumption) if assumption else None

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

    def _set_active_project(self, db, user_id: str, project_id: int) -> None:
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
            "status": project.status,
            "stage": project.stage,
            "channel_id": project.channel_id,
            "integrations": project.integrations,
            "assumptions": [self._serialize_assumption(a) for a in project.assumptions],
            "experiments": [
                {
                    "id": exp.id,
                    "title": exp.title,
                    "method": exp.method,
                    "status": exp.status,
                    "primary_kpi": exp.primary_kpi,
                }
                for exp in project.experiments
            ],
            "members": [{"user_id": member.user_id, "role": member.role} for member in project.members],
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
        }
