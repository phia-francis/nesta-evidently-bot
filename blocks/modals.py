def experiment_modal(assumption_text: str, suggestions: str) -> dict:
    """Build a modal for experiment suggestions."""
    return {
        "type": "modal",
        "title": {"type": "plain_text", "text": "Experiment Ideas"},
        "close": {"type": "plain_text", "text": "Close"},
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"Suggestions for: *{assumption_text}*"},
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": suggestions},
            },
        ],
    }


def decision_room_modal() -> dict:
    """Modal for consensus scoring in the Decision Room."""
    options = [{"text": {"type": "plain_text", "text": str(i)}, "value": str(i)} for i in range(1, 6)]
    return {
        "type": "modal",
        "callback_id": "decision_room_submit",
        "title": {"type": "plain_text", "text": "Decision Session"},
        "submit": {"type": "plain_text", "text": "Reveal"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "assumption_text",
                "label": {"type": "plain_text", "text": "Which assumption are we scoring?"},
                "element": {"type": "plain_text_input", "action_id": "assumption_value"},
            },
            {
                "type": "input",
                "block_id": "impact",
                "label": {"type": "plain_text", "text": "Impact (1 = low, 5 = high)"},
                "element": {"type": "static_select", "action_id": "impact_select", "options": options},
            },
            {
                "type": "input",
                "block_id": "uncertainty",
                "label": {"type": "plain_text", "text": "Uncertainty (1 = low, 5 = high)"},
                "element": {"type": "static_select", "action_id": "uncertainty_select", "options": options},
            },
            {
                "type": "input",
                "block_id": "feasibility",
                "label": {"type": "plain_text", "text": "Feasibility (1 = low, 5 = high)"},
                "element": {"type": "static_select", "action_id": "feasibility_select", "options": options},
            },
        ],
    }
