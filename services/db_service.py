import datetime as dt
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class ProjectDB:
    """Lightweight in-memory placeholder for project data."""

    def __init__(self):
        self._projects: Dict[str, Dict[str, Any]] = {}
        self._user_state: Dict[str, str] = {}

    def get_user_project(self, user_id: str) -> Dict[str, Any]:
        project = self._projects.setdefault(
            user_id,
            {
                "name": "Evidence Backlog",
                "phase": "Discovery",
                "assumptions": [],
                "experiments": [],
                "progress_score": 0,
                "drive_file_id": None,
                "ai_suggestions": [],
                "roadmap": {"now": [], "next": [], "later": []},
                "team": {},
            },
        )
        return project

    def get_current_view(self, user_id: str) -> str:
        """Return the user's current workspace selection."""
        return self._user_state.get(user_id, "overview")

    def set_current_view(self, user_id: str, workspace: str):
        """Persist workspace navigation state."""
        self._user_state[user_id] = workspace

    def save_assumptions(self, user_id: str, assumptions: List[dict]):
        project = self.get_user_project(user_id)
        project["assumptions"] = assumptions
        project["progress_score"] = self._calculate_average_confidence(assumptions)

    def update_assumption_status(self, assumption_id: str, status: str):
        for project in self._projects.values():
            for assumption in project.get("assumptions", []):
                if str(assumption.get("id")) == str(assumption_id):
                    assumption["status"] = status
                    if status == "active":
                        assumption["last_verified_at"] = dt.datetime.utcnow().isoformat()

    def link_drive_file(self, user_id: str, file_id: str):
        project = self.get_user_project(user_id)
        project["drive_file_id"] = file_id

    @staticmethod
    def _calculate_average_confidence(assumptions: List[dict]) -> int:
        active = [a.get("confidence_score") or a.get("confidence") or 0 for a in assumptions if a.get("status") != "archived"]
        if not active:
            return 0
        return round(sum(active) / len(active))
