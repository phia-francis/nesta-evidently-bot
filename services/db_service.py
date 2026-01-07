import logging
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from datetime import datetime, timedelta
from config import Config

# 1. Setup Database Connection
engine = create_engine(Config.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# 2. Define Tables (Schema)
class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, unique=True, index=True) # Slack User ID
    name = Column(String)
    assumptions = relationship("Assumption", back_populates="project")

class Assumption(Base):
    __tablename__ = "assumptions"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    text = Column(Text)
    status = Column(String, default="active") # active, archived, stale
    last_checked = Column(DateTime, default=datetime.utcnow)
    project = relationship("Project", back_populates="assumptions")

# 3. Create Tables (Run this once)
Base.metadata.create_all(bind=engine)

class ProjectDB:
    def get_user_project(self, user_id: str):
        """Fetch a project + assumptions for a user."""
        with SessionLocal() as db:
            project = db.query(Project).filter(Project.user_id == user_id).first()
            
            # If no project exists, create a dummy one for the MVP
            if not project:
                project = Project(user_id=user_id, name="My Innovation Project")
                db.add(project)
                db.commit()
                db.refresh(project)
            
            # Convert to dictionary format for app.py compatibility
            return {
                "id": project.id,
                "name": project.name,
                "assumptions": [{"id": a.id, "text": a.text, "status": a.status} for a in project.assumptions]
            }

    def get_stale_assumptions(self):
        """Find assumptions not checked in X days."""
        limit_date = datetime.utcnow() - timedelta(days=Config.STALE_DAYS)
        with SessionLocal() as db:
            results = db.query(Assumption).filter(
                Assumption.last_checked < limit_date,
                Assumption.status == "active"
            ).all()
            
            return [{"id": a.id, "text": a.text, "user_id": a.project.user_id} for a in results]

    def update_assumption_status(self, assumption_id: int, status: str):
        with SessionLocal() as db:
            assumption = db.query(Assumption).filter(Assumption.id == assumption_id).first()
            if assumption:
                assumption.status = status
                assumption.last_checked = datetime.utcnow()
                db.commit()

    # Helper to add data (for testing)
    def add_assumption(self, user_id, text):
        with SessionLocal() as db:
            project = db.query(Project).filter(Project.user_id == user_id).first()
            if project:
                new_assump = Assumption(project_id=project.id, text=text)
                db.add(new_assump)
                db.commit()
