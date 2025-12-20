"""Block Kit layouts for methods and case studies."""

from typing import List

from services import knowledge_base


def method_cards(stage: str) -> List[dict]:
    methods = knowledge_base.get_stage_methods(stage)
    description = knowledge_base.get_stage_description(stage)
    blocks: List[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": f"{stage.title()} toolkit"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": description or "Nesta Playbook recommendation."}},
    ]
    for method in methods:
        case = knowledge_base.get_case_study(method)
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{method}*\n{case or 'Method rationale coming soon.'}"},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View Case Study"},
                    "action_id": "view_case_study",
                    "value": method,
                },
            }
        )
    return blocks


def case_study_modal(method: str) -> dict:
    case = knowledge_base.get_case_study(method)
    description = case or "Case study not found."
    return {
        "type": "modal",
        "callback_id": "case_study_modal",
        "title": {"type": "plain_text", "text": "Case Study"},
        "close": {"type": "plain_text", "text": "Close"},
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": method}},
            {"type": "section", "text": {"type": "mrkdwn", "text": description}},
        ],
    }
