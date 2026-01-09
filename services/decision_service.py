from slack_sdk.models.blocks import ActionsBlock, DividerBlock, HeaderBlock, SectionBlock
from slack_sdk.models.blocks.elements import Button

from services.db_service import DbService


class DecisionRoomService:
    def __init__(self, db_service: DbService):
        self.db = db_service

    def start_session(self, client, channel_id: str, user_id: str):
        project = self.db.get_active_project(user_id)
        if not project:
            return False, "You need to select a project in the Home Tab first."

        session_id = self.db.create_decision_session(project["id"], channel_id)

        assumptions = [
            assumption
            for assumption in project.get("assumptions", [])
            if assumption.get("status") in ["suggested", "prioritized"]
        ]

        if not assumptions:
            return False, "No pending assumptions to vote on! Add some first."

        blocks = [
            HeaderBlock(text=f"🗳️ Decision Room: {project['name']}").to_dict(),
            SectionBlock(text="*Team Alignment Time!* Vote on which assumptions we should test next.").to_dict(),
            DividerBlock().to_dict(),
        ]

        for assumption in assumptions:
            blocks.append(
                SectionBlock(
                    text=(
                        f"*{assumption['title']}* \n_{assumption['category']}_ "
                        f"| Confidence: {assumption['confidence_score']}%"
                    )
                ).to_dict()
            )
            blocks.append(
                ActionsBlock(
                    elements=[
                        Button(
                            text="✅ Test This",
                            value=f"{session_id}:{assumption['id']}:keep",
                            action_id="vote_keep",
                            style="primary",
                        ),
                        Button(
                            text="⚠️ Pivot",
                            value=f"{session_id}:{assumption['id']}:pivot",
                            action_id="vote_pivot",
                        ),
                        Button(
                            text="🗑️ Kill",
                            value=f"{session_id}:{assumption['id']}:kill",
                            action_id="vote_kill",
                            style="danger",
                        ),
                    ]
                ).to_dict()
            )
            blocks.append(DividerBlock().to_dict())

        blocks.append(
            ActionsBlock(
                elements=[
                    Button(
                        text="🏁 End Session & Tally",
                        value=str(session_id),
                        action_id="end_decision_session",
                        style="primary",
                    )
                ]
            ).to_dict()
        )

        client.chat_postMessage(channel=channel_id, blocks=blocks, text="Decision Room Opened")
        return True, "Session Started"

    def handle_vote(self, body, client):
        user_id = body["user"]["id"]
        session_id, assumption_id, vote_type = body["actions"][0]["value"].split(":")

        self.db.cast_vote(int(session_id), int(assumption_id), user_id, vote_type)

        client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=user_id,
            text=f"Vote cast: {vote_type.upper()} for assumption {assumption_id}",
        )
