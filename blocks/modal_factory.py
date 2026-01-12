from typing import Any


class ModalFactory:
    """Factory for Block Kit payloads used in app workflows."""

    @staticmethod
    def file_analysis_prompt(file_name: str, file_id: str) -> list[dict[str, Any]]:
        return [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"📄 *Analyse {file_name}?*"},
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Yes, Auto-fill Canvas"},
                        "action_id": "analyze_file",
                        "value": file_id,
                        "style": "primary",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "No, ignore"},
                        "action_id": "ignore_file",
                    },
                ],
            },
        ]

    @staticmethod
    def document_insights_blocks(
        canvas_data: dict[str, Any],
        gaps: list[str],
        follow_ups: list[str],
    ) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = [
            {"type": "header", "text": {"type": "plain_text", "text": "📄 Document Insights"}},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Problem:* {canvas_data.get('problem') or '—'}\n"
                        f"*Solution:* {canvas_data.get('solution') or '—'}\n"
                        f"*Users:* {', '.join(canvas_data.get('users', [])) or '—'}"
                    ),
                },
            },
            {"type": "divider"},
        ]
        if gaps:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "*Gaps Identified:*\n" + "\n".join([f"• {gap}" for gap in gaps])},
                }
            )
        if follow_ups:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Follow-up Questions:*\n" + "\n".join([f"• {q}" for q in follow_ups]),
                    },
                }
            )
        return blocks

    @staticmethod
    def suggested_assumption_blocks(risk: str, payload: str) -> list[dict[str, Any]]:
        return [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"💡 *Suggested Assumption:*\n{risk}"},
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ Add to Board"},
                        "value": payload,
                        "action_id": "accept_suggestion",
                        "style": "primary",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✏️ Edit"},
                        "value": payload,
                        "action_id": "edit_suggestion",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "❌ Reject"},
                        "value": payload,
                        "action_id": "reject_suggestion",
                    },
                ],
            },
        ]
