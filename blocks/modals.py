_MAX_ROADMAP_MODAL_TITLE_LENGTH = 75


def _truncate_text(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


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


def open_log_assumption_modal(ai_data: dict | None = None) -> dict:
    ai_data = ai_data or {}
    blocks = []
    if ai_data.get("text"):
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "✨ AI drafted this based on your conversation. Edit before saving.",
                    }
                ],
            }
        )
    return {
        "type": "modal",
        "callback_id": "create_assumption_submit",
        "private_metadata": "ai_draft",
        "title": {"type": "plain_text", "text": "Log Assumption"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            *blocks,
            {
                "type": "input",
                "block_id": "assumption_text",
                "label": {
                    "type": "plain_text",
                    "text": "What are you assuming or testing? (e.g., 'We think parents will use the app if it's free')",
                },
                "element": {
                    "type": "plain_text_input",
                    "action_id": "assumption_text_input",
                    "multiline": True,
                    "initial_value": _truncate_text(ai_data.get("text", ""), 2900),
                },
            },
        ],
    }


def get_diagnostic_modal(
    ocp_questions: dict[str, dict[str, str]],
    project_id: int,
    ai_data: dict[str, dict[str, object]] | None = None,
    status_message: str | None = None,
) -> dict:
    options = [{"text": {"type": "plain_text", "text": str(i)}, "value": str(i)} for i in range(1, 6)]

    ai_data = ai_data or {}
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Rate confidence (1 = low, 5 = high) for each OCP diagnostic question.",
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✨ Auto-Fill with AI"},
                    "action_id": "autofill_diagnostic",
                    "value": str(project_id),
                }
            ],
        },
        {"type": "divider"},
    ]
    if status_message:
        blocks.insert(
            1,
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": status_message}],
            },
        )

    for category, questions in ocp_questions.items():
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{category}*"},
            }
        )
        for key, question in questions.items():
            ai_key = f"{category.lower()}_{key.lower()}"
            ai_answer = ai_data.get(ai_key, {})
            initial_answer = str(ai_answer.get("answer", "")) if ai_answer else ""
            initial_confidence = str(ai_answer.get("confidence", "")) if ai_answer else ""
            initial_option = next((option for option in options if option["value"] == initial_confidence), None)
            blocks.append(
                {
                    "type": "input",
                    "block_id": f"ocp_answer__{category.lower()}__{key.lower()}",
                    "label": {"type": "plain_text", "text": question},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "answer",
                        "multiline": True,
                        "initial_value": initial_answer,
                    },
                }
            )
            blocks.append(
                {
                    "type": "input",
                    "block_id": f"ocp_confidence__{category.lower()}__{key.lower()}",
                    "label": {"type": "plain_text", "text": "Confidence (1-5)"},
                    "element": {
                        "type": "static_select",
                        "action_id": "confidence_score",
                        "options": options,
                        "initial_option": initial_option,
                    },
                }
            )
        blocks.append({"type": "divider"})

    return {
        "type": "modal",
        "callback_id": "action_save_diagnostic",
        "private_metadata": str(project_id),
        "title": {"type": "plain_text", "text": "Run Diagnostic"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }


def get_new_project_modal() -> dict:
    stage_options = [
        {"text": {"type": "plain_text", "text": "Audit"}, "value": "audit"},
        {"text": {"type": "plain_text", "text": "Plan"}, "value": "plan"},
        {"text": {"type": "plain_text", "text": "Action"}, "value": "action"},
    ]
    return {
        "type": "modal",
        "callback_id": "new_project_submit",
        "title": {"type": "plain_text", "text": "New Project"},
        "submit": {"type": "plain_text", "text": "Create"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "project_name",
                "label": {"type": "plain_text", "text": "Project Name"},
                "element": {"type": "plain_text_input", "action_id": "value"},
            },
            {
                "type": "input",
                "block_id": "project_description",
                "label": {"type": "plain_text", "text": "Description"},
                "element": {"type": "plain_text_input", "action_id": "value", "multiline": True},
            },
            {
                "type": "input",
                "block_id": "project_flow_stage",
                "label": {"type": "plain_text", "text": "Initial Stage"},
                "element": {
                    "type": "static_select",
                    "action_id": "value",
                    "options": stage_options,
                    "initial_option": stage_options[0],
                },
            },
        ],
    }


def get_roadmap_modal(assumptions: list[dict]) -> dict:
    assumption_options = [
        {
            "text": {
                "type": "plain_text",
                "text": _truncate_text(item.get("title", "Untitled"), _MAX_ROADMAP_MODAL_TITLE_LENGTH),
            },
            "value": str(item["id"]),
        }
        for item in assumptions
    ]
    horizon_options = [
        {"text": {"type": "plain_text", "text": "Now"}, "value": "now"},
        {"text": {"type": "plain_text", "text": "Next"}, "value": "next"},
        {"text": {"type": "plain_text", "text": "Later"}, "value": "later"},
    ]
    initial_assumption = assumption_options[0] if assumption_options else None
    initial_horizon = horizon_options[0]

    return {
        "type": "modal",
        "callback_id": "save_roadmap_horizon",
        "title": {"type": "plain_text", "text": "Update Roadmap"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "roadmap_assumption_select",
                "label": {"type": "plain_text", "text": "Select assumption"},
                "element": {
                    "type": "static_select",
                    "action_id": "assumption_id",
                    "options": assumption_options,
                    "initial_option": initial_assumption,
                },
            },
            {
                "type": "input",
                "block_id": "roadmap_horizon_select",
                "label": {"type": "plain_text", "text": "Move to horizon"},
                "element": {
                    "type": "static_select",
                    "action_id": "horizon",
                    "options": horizon_options,
                    "initial_option": initial_horizon,
                },
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


SCORE_OPTIONS = [
    {"text": {"type": "plain_text", "text": f"{i} - {desc}"}, "value": str(i)}
    for i, desc in [
        (0, "None"),
        (1, "Very Low"),
        (2, "Low"),
        (3, "Medium"),
        (4, "High"),
        (5, "Critical"),
    ]
]

EVIDENCE_OPTIONS = [
    {"text": {"type": "plain_text", "text": f"Level {i} - {desc}"}, "value": str(i)}
    for i, desc in [
        (0, "No evidence"),
        (1, "Light evidence (Say)"),
        (2, "Light action (Do)"),
        (3, "Strong action (Do)"),
        (4, "Market proof"),
        (5, "Validated"),
    ]
]


def silent_scoring_modal(assumption_title: str, session_id: int, assumption_id: int) -> dict:
    """Implements the Silent Scoring phase with multi-criteria ratings."""

    return {
        "type": "modal",
        "callback_id": "submit_silent_score",
        "private_metadata": f"{session_id}:{assumption_id}",
        "title": {"type": "plain_text", "text": "🗳️ Silent Scoring"},
        "submit": {"type": "plain_text", "text": "Submit Score"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"Scoring Assumption:\n*{assumption_title}*"},
            },
            {"type": "divider"},
            {
                "type": "input",
                "block_id": "impact_block",
                "label": {"type": "plain_text", "text": "Impact (if true, how big is the win?)"},
                "element": {
                    "type": "static_select",
                    "action_id": "impact_score",
                    "options": SCORE_OPTIONS,
                    "initial_option": SCORE_OPTIONS[3],
                },
            },
            {
                "type": "input",
                "block_id": "uncertainty_block",
                "label": {"type": "plain_text", "text": "Uncertainty (how much do we NOT know?)"},
                "element": {
                    "type": "static_select",
                    "action_id": "uncertainty_score",
                    "options": SCORE_OPTIONS,
                },
            },
            {
                "type": "input",
                "block_id": "feasibility_block",
                "label": {"type": "plain_text", "text": "Feasibility (can we act on it?)"},
                "element": {
                    "type": "static_select",
                    "action_id": "feasibility_score",
                    "options": SCORE_OPTIONS,
                },
            },
            {
                "type": "input",
                "block_id": "evidence_block",
                "label": {"type": "plain_text", "text": "Current Evidence Level"},
                "element": {
                    "type": "static_select",
                    "action_id": "confidence_score",
                    "options": EVIDENCE_OPTIONS,
                    "initial_option": EVIDENCE_OPTIONS[0],
                },
            },
            {
                "type": "input",
                "optional": True,
                "block_id": "rationale_block",
                "label": {"type": "plain_text", "text": "Rationale (Optional)"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "rationale_text",
                    "multiline": True,
                    "placeholder": "Why did you score it this way?",
                },
            },
        ],
    }

def invite_member_modal() -> dict:
    return {
        "type": "modal",
        "callback_id": "invite_member_submit",
        "title": {"type": "plain_text", "text": "Invite teammate"},
        "submit": {"type": "plain_text", "text": "Add"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "member_select",
                "label": {"type": "plain_text", "text": "Choose a teammate"},
                "element": {"type": "users_select", "action_id": "selected_member"},
            }
        ],
    }


def link_channel_modal() -> dict:
    return {
        "type": "modal",
        "callback_id": "link_channel_submit",
        "title": {"type": "plain_text", "text": "Link channel"},
        "submit": {"type": "plain_text", "text": "Link"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Pick an existing channel for project updates and Decision Room voting.",
                },
            },
            {
                "type": "input",
                "block_id": "channel_select",
                "label": {"type": "plain_text", "text": "Channel"},
                "element": {"type": "channels_select", "action_id": "selected_channel"},
            },
            {
                "type": "input",
                "optional": True,
                "block_id": "tab_template",
                "label": {"type": "plain_text", "text": "Channel tabs template"},
                "element": {
                    "type": "checkboxes",
                    "action_id": "tab_options",
                    "options": [
                        {"text": {"type": "plain_text", "text": "Experiments"}, "value": "experiments"},
                        {"text": {"type": "plain_text", "text": "Manual"}, "value": "manual"},
                        {"text": {"type": "plain_text", "text": "Decisions"}, "value": "decisions"},
                    ],
                },
            },
        ],
    }


def create_channel_modal(project_name: str) -> dict:
    return {
        "type": "modal",
        "callback_id": "create_channel_submit",
        "title": {"type": "plain_text", "text": "New project channel"},
        "submit": {"type": "plain_text", "text": "Create"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "channel_name",
                "label": {"type": "plain_text", "text": "Channel name"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "channel_input",
                    "initial_value": project_name.lower().replace(" ", "-"),
                },
            },
            {
                "type": "input",
                "optional": True,
                "block_id": "member_select",
                "label": {"type": "plain_text", "text": "Invite teammates"},
                "element": {"type": "multi_users_select", "action_id": "selected_members"},
            },
            {
                "type": "input",
                "optional": True,
                "block_id": "tab_template",
                "label": {"type": "plain_text", "text": "Channel tabs template"},
                "element": {
                    "type": "checkboxes",
                    "action_id": "tab_options",
                    "options": [
                        {"text": {"type": "plain_text", "text": "Experiments"}, "value": "experiments"},
                        {"text": {"type": "plain_text", "text": "Manual"}, "value": "manual"},
                        {"text": {"type": "plain_text", "text": "Decisions"}, "value": "decisions"},
                    ],
                },
            },
        ],
    }


def extract_insights_modal() -> dict:
    return {
        "type": "modal",
        "callback_id": "extract_insights_submit",
        "title": {"type": "plain_text", "text": "Extract insights"},
        "submit": {"type": "plain_text", "text": "Run"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Choose a channel and paste a message link to analyse its thread.",
                },
            },
            {
                "type": "input",
                "block_id": "channel_select",
                "label": {"type": "plain_text", "text": "Channel"},
                "element": {"type": "channels_select", "action_id": "channel_input"},
            },
            {
                "type": "input",
                "optional": True,
                "block_id": "message_link",
                "label": {"type": "plain_text", "text": "Message link"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "message_input",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Paste a Slack message link to analyse the thread.",
                    },
                },
            },
        ],
    }


def get_loading_modal() -> dict:
    """Returns a temporary modal to show while AI is processing."""
    return {
        "type": "modal",
        "callback_id": "loading_modal",
        "title": {"type": "plain_text", "text": "Evidently AI"},
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": "🧠 *Analyzing context...*"}},
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            "Identifying assumptions and extracting evidence from the thread. "
                            "This may take a few seconds."
                        ),
                    }
                ],
            },
        ],
    }


def add_canvas_item_modal(section: str) -> dict:
    return {
        "type": "modal",
        "callback_id": "add_canvas_item_submit",
        "private_metadata": section,
        "title": {"type": "plain_text", "text": "Add Canvas Item"},
        "submit": {"type": "plain_text", "text": "Add"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"Add a new item to *{section}*."},
            },
            {
                "type": "input",
                "block_id": "canvas_text",
                "label": {"type": "plain_text", "text": "Item"},
                "element": {"type": "plain_text_input", "action_id": "canvas_input", "multiline": True},
            },
        ],
    }


def change_stage_modal(current_stage: str) -> dict:
    options = [
        {"text": {"type": "plain_text", "text": label}, "value": value}
        for label, value in [
            ("Define", "Define"),
            ("Develop", "Develop"),
            ("Refine", "Refine"),
            ("Evaluate", "Evaluate"),
            ("Diffuse", "Diffuse"),
        ]
    ]
    initial = next((option for option in options if option["value"] == current_stage), options[0])
    return {
        "type": "modal",
        "callback_id": "change_stage_submit",
        "title": {"type": "plain_text", "text": "Change Stage"},
        "submit": {"type": "plain_text", "text": "Update"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "stage_select",
                "label": {"type": "plain_text", "text": "Stage"},
                "element": {
                    "type": "static_select",
                    "action_id": "stage_input",
                    "options": options,
                    "initial_option": initial,
                },
            }
        ],
    }
