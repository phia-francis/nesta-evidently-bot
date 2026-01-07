import logging
import datetime as dt
from typing import List, Dict, Any, Optional
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, Enum, Float, JSON
from sqlalchemy.orm import sessionmaker, declarative_base, relationship, joinedload
from config import Config

# 1. Setup Database Connection
engine = create_engine(Config.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# 2. Define Tables (Schema)
class Project(Base):
    __tablename__ = "projects"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(255), unique=True, index=True)  # Added length
    name = Column(String(255), default="Evidence Backlog")
    phase = Column(String(50), default="Discovery")         # Restored field
    progress_score = Column(Integer, default=0)             # Restored field
    drive_file_id = Column(String(255), nullable=True)      # Restored field
    current_view = Column(String(50), default="overview")   # To persist UI state
    
    # Store complex structures as JSON for MVP simplicity
    experiments = Column(JSON, default=list)
    ai_suggestions = Column(JSON, default=list)
    roadmap = Column(JSON, default=lambda: {"now": [], "next": [], "later": []})
    team = Column(JSON, default=dict)

    assumptions = relationship("Assumption", back_populates="project", cascade="all, delete-orphan")

class Assumption(Base):
    __tablename__ = "assumptions"
    
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    text = Column(Text)
    category = Column(String(100), nullable=True)           # Restored field
    confidence_score = Column(Integer, default=0)           # Restored field
    status = Column(Enum("active", "archived", "stale", name="assumption_status_enum"), default="active")
    last_checked = Column(DateTime, default=dt.datetime.utcnow)
    last_verified_at = Column(DateTime, nullable=True)
    
    project = relationship("Project", back_populates="assumptions")

# 3. Create Tables
# Note: In production, use Alembic for migrations instead of create_all
Base.metadata.create_all(bind=engine)

class ProjectDB:
    def get_user_project(self, user_id: str) -> Dict[str, Any]:
        """Fetch a project + assumptions for a user, matching old API structure."""
        with SessionLocal() as db:
            project = db.query(Project).options(joinedload(Project.assumptions)).filter(Project.user_id == user_id).first()
            
            if not project:
                project = Project(user_id=user_id)
                db.add(project)
                db.commit()
                db.refresh(project)
            
            # Reconstruct the dictionary structure expected by app.py
            return {
                "id": project.id,
                "name": project.name,
                "phase": project.phase,
                "progress_score": project.progress_score,
                "drive_file_id": project.drive_file_id,
                "experiments": project.experiments,
                "ai_suggestions": project.ai_suggestions,
                "roadmap": project.roadmap,
                "team": project.team,
                "assumptions": [
                    {
                        "id": str(a.id), # Convert to string if UI expects strings
                        "text": a.text,
                        "status": a.status,
                        "category": a.category,
                        "confidence_score": a.confidence_score,
                        "last_verified_at": a.last_verified_at.isoformat() if a.last_verified_at else None
                    } 
                    for a in project.assumptions
                ]
            }

    def get_current_view(self, user_id: str) -> str:
        """Return the user's current workspace selection."""
        with SessionLocal() as db:
            project = db.query(Project).filter(Project.user_id == user_id).first()
            return project.current_view if project else "overview"

    def set_current_view(self, user_id: str, workspace: str):
        """Persist workspace navigation state."""
        with SessionLocal() as db:
            project = db.query(Project).filter(Project.user_id == user_id).first()
            if project:
                project.current_view = workspace
                db.commit()

    def link_drive_file(self, user_id: str, file_id: str):
        """Link a Google Drive file to the project."""
        with SessionLocal() as db:
            project = db.query(Project).filter(Project.user_id == user_id).first()
            if project:
                project.drive_file_id = file_id
                db.commit()
                
    def save_assumptions(self, user_id: str, assumptions: List[Dict[str, Any]]):
        """Saves a list of assumptions, replacing existing ones for the user."""
        with SessionLocal() as db:
            project = db.query(Project).options(joinedload(Project.assumptions)).filter(Project.user_id == user_id).first()
            if not project:
                project = Project(user_id=user_id)
                db.add(project)
                db.flush()

            project.assumptions.clear()
            new_assumption_objects = [
                Assumption(
                    project_id=project.id,
                    text=ass_data.get("text"),
                    category=ass_data.get("category"),
                    confidence_score=ass_data.get("confidence_score") or ass_data.get("confidence", 0),
                    status=ass_data.get("status", "active"),
                ) for ass_data in assumptions
            ]
            project.assumptions.extend(new_assumption_objects)
            project.progress_score = self._calculate_average_confidence(assumptions)

            db.commit()
    
    def update_assumption_status(self, assumption_id: str, status: str):
        with SessionLocal() as db:
            # Handle potential string input from UI
            try:
                a_id = int(assumption_id)
            except ValueError:
                logging.error(f"Invalid assumption ID: {assumption_id}")
                return

            assumption = db.query(Assumption).filter(Assumption.id == a_id).first()
            if assumption:
                assumption.status = status
                assumption.last_checked = dt.datetime.utcnow()
                if status == "active":
                    assumption.last_verified_at = dt.datetime.utcnow()
                db.commit()

    def get_stale_assumptions(self):
        """Find assumptions not checked in X days (Optimized)."""
        limit_date = dt.datetime.utcnow() - dt.timedelta(days=Config.STALE_DAYS)
        with SessionLocal() as db:
            # Fix N+1 query problem by eager loading the project relationship
            results = db.query(Assumption).options(joinedload(Assumption.project)).filter(
                Assumption.last_checked < limit_date,
                Assumption.status == "active"
            ).all()
            
            return [
                {"id": a.id, "text": a.text, "user_id": a.project.user_id} 
                for a in results if a.project # Check if project exists
            ]

    def _calculate_average_confidence(self, assumptions: List[Any]) -> int:
        """Internal helper to calc score based on assumption objects or dicts."""
        # Handle both SQLAlchemy objects and dictionaries
        active_scores = []
        for a in assumptions:
            status = getattr(a, 'status', None) or a.get('status')
            if status != 'archived':
                score = getattr(a, 'confidence_score', None) or a.get('confidence_score', 0)
                active_scores.append(score)
        
        if not active_scores:
            return 0
        return round(sum(active_scores) / len(active_scores))
