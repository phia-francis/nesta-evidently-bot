import statistics

from slack_sdk.models.blocks import ActionsBlock, DividerBlock, HeaderBlock, SectionBlock
from slack_sdk.models.blocks.block_elements import ButtonElement as Button
from slack_sdk.models.blocks import PlainTextObject

from services.db_service import DbService

DISAGREEMENT_STD_DEV_THRESHOLD = 1.2


class DecisionRoomService:
    def __init__(self, db_service: DbService):
        self.db = db_service

    def start_session(
        self,
        channel_id: str,
        client=None,
        user_id: str | None = None,
    ) -> tuple[bool, str, int | None]:
        if user_id:
            project = self.db.get_active_project(user_id)
        else:
            project = self.db.get_project_by_channel(channel_id)
        if not project:
            return False, "You need to select a project in the Home Tab first.", None

        session_id = self.db.create_decision_session(project["id"], channel_id)

        assumptions = [
            assumption
            for assumption in project.get("assumptions", [])
            if assumption.get("validation_status") != "Rejected"
        ]

        if not assumptions:
            return False, "No pending assumptions to vote on! Add some first.", session_id

        blocks = [
            HeaderBlock(text=f"🗳️ Decision Room: {project['name']}").to_dict(),
            SectionBlock(
                text=(
                    "*Silent Scoring is live.* Rate each assumption privately across impact, uncertainty, "
                    "feasibility, and evidence level."
                )
            ).to_dict(),
            DividerBlock().to_dict(),
        ]

        for assumption in assumptions:
            blocks.append(
                SectionBlock(text=(f"*{assumption['title']}* \nStatus: {assumption['validation_status']}")).to_dict()
            )
            blocks.append(
                ActionsBlock(
                    elements=[
                        Button(
                            text=PlainTextObject(text="📝 Score privately"),
                            value=f"{session_id}:{assumption['id']}",
                            action_id="open_silent_score",
                            style="primary",
                        ),
                    ]
                ).to_dict()
            )
            blocks.append(DividerBlock().to_dict())

        blocks.append(
            ActionsBlock(
                elements=[
                    Button(
                        text=PlainTextObject(text="🏁 End Session & Tally"),
                        value=str(session_id),
                        action_id="end_decision_session",
                        style="primary",
                    )
                ]
            ).to_dict()
        )

        if client:
            client.chat_postMessage(channel=channel_id, blocks=blocks, text="Decision Room Opened")
        return True, "Session Started", session_id

    def record_vote(
        self,
        assumption_id: int,
        user_id: str,
        impact_score: int,
        uncertainty_score: int,
    ) -> None:
        self.db.record_decision_vote(
            assumption_id=assumption_id,
            user_id=user_id,
            impact=impact_score,
            uncertainty=uncertainty_score,
        )

    def reveal_results(self, assumption_id: int) -> dict:
        summary = self.db.get_decision_vote_summary(assumption_id)
        avg_impact = summary.get("avg_impact", 0.0)
        avg_uncertainty = summary.get("avg_uncertainty", 0.0)
        if avg_impact >= 4 and avg_uncertainty >= 4:
            guidance = "High Impact, High Uncertainty → Do this first."
        elif avg_impact >= 4 and avg_uncertainty < 4:
            guidance = "High Impact, Lower Uncertainty → Move quickly."
        elif avg_impact < 4 and avg_uncertainty >= 4:
            guidance = "Lower Impact, High Uncertainty → Park and learn."
        else:
            guidance = "Lower Impact, Lower Uncertainty → Schedule later."

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*Decision Room Summary*\n"
                        f"Average Impact: {avg_impact:.2f}\n"
                        f"Average Uncertainty: {avg_uncertainty:.2f}\n"
                        f"{guidance}"
                    ),
                },
            }
        ]
        return {
            "avg_impact": avg_impact,
            "avg_uncertainty": avg_uncertainty,
            "count": summary.get("count", 0),
            "guidance": guidance,
            "blocks": blocks,
        }

    def reveal_scores(self, session_id: int) -> dict[int, dict[str, float | int | bool]]:
        scores = self.db.get_session_scores(session_id)
        results: dict[int, dict[str, float | int | bool]] = {}

        for assumption_id, score_list in scores.items():
            impacts = [s.impact for s in score_list if s.impact is not None]
            uncertainties = [s.uncertainty for s in score_list if s.uncertainty is not None]
            feasibilities = [s.feasibility for s in score_list if s.feasibility is not None]
            confidences = [s.confidence for s in score_list if s.confidence is not None]

            impact_std = statistics.stdev(impacts) if len(impacts) > 1 else 0
            uncertainty_std = statistics.stdev(uncertainties) if len(uncertainties) > 1 else 0
            feasibility_std = statistics.stdev(feasibilities) if len(feasibilities) > 1 else 0

            disagreement_flag = max(impact_std, uncertainty_std, feasibility_std) > DISAGREEMENT_STD_DEV_THRESHOLD

            results[assumption_id] = {
                "avg_impact": statistics.mean(impacts) if impacts else 0,
                "avg_uncertainty": statistics.mean(uncertainties) if uncertainties else 0,
                "avg_feasibility": statistics.mean(feasibilities) if feasibilities else 0,
                "avg_confidence": statistics.mean(confidences) if confidences else 0,
                "disagreement": disagreement_flag,
                "count": len(score_list),
            }

        return results
