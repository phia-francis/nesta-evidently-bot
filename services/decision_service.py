import time
import uuid


class DecisionRoom:
    def __init__(self):
        # In-memory storage; swap for persistent cache in production.
        self.sessions: dict[str, dict] = {}
        self._latest_session_by_channel: dict[str, str] = {}

    def create_session(self, channel_id: str, topic: str) -> str:
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = {
            "topic": topic,
            "channel": channel_id,
            "status": "voting",
            "votes": {},
            "created_at": time.time(),
        }
        self._latest_session_by_channel[channel_id] = session_id
        return session_id

    def get_active_session(self, channel_id: str) -> str | None:
        session_id = self._latest_session_by_channel.get(channel_id)
        session = self.sessions.get(session_id) if session_id else None
        if session and session.get("status") == "voting":
            return session_id
        return None

    def cast_vote(self, session_id: str, user_id: str, impact: int, uncertainty: int) -> bool:
        session = self.sessions.get(session_id)
        if not session:
            return False
        session["votes"][user_id] = {"impact": impact, "uncertainty": uncertainty}
        return True

    def get_votes(self, session_id: str) -> list[dict]:
        session = self.sessions.get(session_id)
        if not session:
            return []
        return [
            {"user_id": user, "impact": vote.get("impact", 0), "uncertainty": vote.get("uncertainty", 0)}
            for user, vote in session.get("votes", {}).items()
        ]

    def reveal_votes(self, session_id: str) -> dict | None:
        session = self.sessions.get(session_id)
        if not session:
            return None

        votes = session["votes"].values()
        if not votes:
            return {"avg_impact": 0, "avg_uncertainty": 0, "count": 0}

        avg_imp = sum(v["impact"] for v in votes) / len(votes)
        avg_unc = sum(v["uncertainty"] for v in votes) / len(votes)

        session["status"] = "revealed"
        return {
            "avg_impact": round(avg_imp, 1),
            "avg_uncertainty": round(avg_unc, 1),
            "count": len(votes),
        }
