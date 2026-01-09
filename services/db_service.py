import datetime as dt
from typing import Any, Dict, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, create_engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import declarative_base, joinedload, relationship, sessionmaker

from config import Config

# 1. Setup Database
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


# --- 1. CORE ENTITIES (Aligned with React types.ts) ---


class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255))
    description = Column(Text, nullable=True)
    status = Column(String(50), default="active")
    created_by = Column(String(255))
    created_at = Column(DateTime, default=dt.datetime.utcnow)
    phase = Column(String(50), default="Discovery")

    # Innovation Health Metrics
    innovation_score = Column(Integer, default=0)
    velocity = Column(Integer, default=0)

    members = relationship("ProjectMember", back_populates="project", cascade="all, delete-orphan")
    assumptions = relationship("Assumption", back_populates="project", cascade="all, delete-orphan")
    experiments = relationship("Experiment", back_populates="project", cascade="all, delete-orphan")
    decisions = relationship("DecisionSession", back_populates="project")


class ProjectMember(Base):
    __tablename__ = "project_members"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    user_id = Column(String(255), index=True)
    role = Column(String(50), default="member")
    project = relationship("Project", back_populates="members")


class Assumption(Base):
    __tablename__ = "assumptions"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))

    # Core Content
    title = Column(String(255))
    description = Column(Text, nullable=True)

    # The "Evidently" Taxonomy
    category = Column(String(50))
    status = Column(String(50), default="suggested")
    lane = Column(String(50), default="backlog")

    # Scoring (0-100)
    confidence_score = Column(Integer, default=0)
    evidence_score = Column(Integer, default=0)
    impact_score = Column(Integer, default=0)

    # Metadata
    provenance = Column(JSON, default=list)
    tags = Column(JSON, default=list)

    project = relationship("Project", back_populates="assumptions")
    experiments = relationship("Experiment", back_populates="assumption")
    votes = relationship("DecisionVote", back_populates="assumption")


class Experiment(Base):
    __tablename__ = "experiments"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    assumption_id = Column(Integer, ForeignKey("assumptions.id"), nullable=True)

    title = Column(String(255))
    method = Column(String(100))
    status = Column(String(50), default="planning")

    # Scientific Method
    hypothesis = Column(Text)
    metrics = Column(JSON, default=dict)

    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)

    project = relationship("Project", back_populates="experiments")
    assumption = relationship("Assumption", back_populates="experiments")


# --- 2. DECISION ROOM ENTITIES ---


class DecisionSession(Base):
    """Represents a live voting round in Slack."""

    __tablename__ = "decision_sessions"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    channel_id = Column(String(255))
    status = Column(String(50), default="active")
    created_at = Column(DateTime, default=dt.datetime.utcnow)

    project = relationship("Project", back_populates="decisions")
    votes = relationship("DecisionVote", back_populates="session")


class DecisionVote(Base):
    __tablename__ = "decision_votes"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("decision_sessions.id"))
    assumption_id = Column(Integer, ForeignKey("assumptions.id"))
    user_id = Column(String(255))

    vote_type = Column(String(50))
    value_score = Column(Integer, nullable=True)

    session = relationship("DecisionSession", back_populates="votes")
    assumption = relationship("Assumption", back_populates="votes")


# Create Tables
Base.metadata.create_all(bind=engine)


# --- 3. UPDATED SERVICE CLASS ---
class DbService:
    def create_project(
        self,
        user_id: str,
        name: str,
        description: str | None = None,
        phase: str = "Discovery",
    ) -> Project:
        with SessionLocal() as db:
            project = Project(name=name, description=description, phase=phase, created_by=user_id)
            db.add(project)
            db.commit()
            db.refresh(project)

            member = ProjectMember(project_id=project.id, user_id=user_id, role="owner")
            db.add(member)
            db.commit()
            db.refresh(project)
            return project

    def get_active_project(self, user_id: str) -> Optional[Dict[str, Any]]:
        with SessionLocal() as db:
            membership = db.query(ProjectMember).filter(ProjectMember.user_id == user_id).first()
            if not membership or not membership.project:
                return None

            project = (
                db.query(Project)
                .options(
                    joinedload(Project.assumptions),
                    joinedload(Project.experiments),
                    joinedload(Project.members),
                )
                .filter(Project.id == membership.project_id)
                .first()
            )
            return self._serialize_project(project) if project else None

    def get_user_projects(self, user_id: str) -> list[dict]:
        with SessionLocal() as db:
            memberships = db.query(ProjectMember).options(joinedload(ProjectMember.project)).filter(
                ProjectMember.user_id == user_id
            ).all()
            return [{"name": m.project.name, "id": m.project_id} for m in memberships if m.project]

    def create_assumption(self, project_id: int, data: dict) -> Assumption:
        with SessionLocal() as db:
            assumption = Assumption(
                project_id=project_id,
                title=data.get("title"),
                description=data.get("description"),
                category=data.get("category", "desirability"),
                confidence_score=data.get("confidence", 0),
                evidence_score=data.get("evidence", 0),
                impact_score=data.get("impact", 0),
                status=data.get("status", "suggested"),
                lane=data.get("lane", "backlog"),
                provenance=data.get("provenance", []),
                tags=data.get("tags", []),
            )
            db.add(assumption)
            db.commit()
            db.refresh(assumption)
            return assumption

    def update_assumption_status(self, assumption_id: int, status: str) -> None:
        with SessionLocal() as db:
            assumption = db.query(Assumption).filter(Assumption.id == assumption_id).first()
            if not assumption:
                return
            assumption.status = status
            db.commit()

    def update_assumption_lane(self, assumption_id: int, lane: str) -> None:
        with SessionLocal() as db:
            assumption = db.query(Assumption).filter(Assumption.id == assumption_id).first()
            if not assumption:
                return
            assumption.lane = lane
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

    def cast_vote(self, session_id: int, assumption_id: int, user_id: str, vote_type: str) -> None:
        with SessionLocal() as db:
            vote = (
                db.query(DecisionVote)
                .filter_by(session_id=session_id, assumption_id=assumption_id, user_id=user_id)
                .first()
            )

            if not vote:
                vote = DecisionVote(session_id=session_id, assumption_id=assumption_id, user_id=user_id)
                db.add(vote)

            vote.vote_type = vote_type
            db.commit()

    def get_session_results(self, session_id: int) -> Dict[int, Dict[str, int]]:
        with SessionLocal() as db:
            votes = db.query(DecisionVote).filter(DecisionVote.session_id == session_id).all()
            results: Dict[int, Dict[str, int]] = {}
            for vote in votes:
                if vote.assumption_id not in results:
                    results[vote.assumption_id] = {"keep": 0, "kill": 0, "pivot": 0}
                if vote.vote_type in results[vote.assumption_id]:
                    results[vote.assumption_id][vote.vote_type] += 1
            return results

    def _serialize_project(self, project: Project) -> Dict[str, Any]:
        return {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "status": project.status,
            "phase": project.phase,
            "innovation_score": project.innovation_score,
            "velocity": project.velocity,
            "assumptions": [self._serialize_assumption(a) for a in project.assumptions],
            "experiments": [
                {
                    "id": exp.id,
                    "title": exp.title,
                    "method": exp.method,
                    "status": exp.status,
                }
                for exp in project.experiments
            ],
            "members": [{"user_id": member.user_id, "role": member.role} for member in project.members],
        }

    def _serialize_assumption(self, assumption: Assumption) -> Dict[str, Any]:
        return {
            "id": assumption.id,
            "title": assumption.title,
            "description": assumption.description,
            "category": assumption.category,
            "status": assumption.status,
            "lane": assumption.lane,
            "confidence_score": assumption.confidence_score,
            "evidence_score": assumption.evidence_score,
            "impact_score": assumption.impact_score,
            "provenance": assumption.provenance,
            "tags": assumption.tags,
        }
