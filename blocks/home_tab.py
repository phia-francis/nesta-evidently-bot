from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from blocks.ui_manager import UIManager
from services.playbook_service import PlaybookService


_OCP_CATEGORIES = ("Opportunity", "Capability", "Progress")
_FLOW_STAGE_LABELS = {
    "audit": "Audit",
    "plan": "Plan",
    "action": "Action",
}
_MAX_TEXT_LENGTH = 2900
_MAX_PROJECT_NAME_LENGTH_SLACK_UI = 75
_STALE_ASSUMPTION_THRESHOLD_DAYS = 30
_LOW_CONFIDENCE_THRESHOLD = 3


def _truncate(text: str) -> str:
    if len(text) <= _MAX_TEXT_LENGTH:
        return text
    return text[: _MAX_TEXT_LENGTH - 3] + "..."


def _safe_button(
    text: str,
    action_id: str,
    value: str | int | None = None,
    style: str | None = None,
) -> dict[str, Any]:
    button: dict[str, Any] = {
        "type": "button",
        "text": {"type": "plain_text", "text": text},
        "action_id": action_id,
    }
    if value is not None:
        button["value"] = str(value)
    if style in {"primary", "danger"}:
        button["style"] = style
    return button


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _status_emoji(status: str, is_stale: bool) -> str:
    if is_stale:
        return "⚠️"
    if status == "Validated":
        return "✅"
    if status == "Rejected":
        return "❌"
    return "🧪"


def _confidence_label(confidence: int | None) -> tuple[str, bool]:
    if confidence in (None, 0):
        return "Unscored", False
    is_low = confidence < _LOW_CONFIDENCE_THRESHOLD
    return f"{confidence}/5", is_low


def _assumption_section(assumption: dict[str, Any], highlight_low_confidence: bool = False) -> dict[str, Any]:
    status = assumption.get("status") or assumption.get("validation_status") or "Testing"
    last_tested = _parse_datetime(assumption.get("last_tested_at")) or _parse_datetime(assumption.get("updated_at"))
    is_stale = False
    if status == "Testing" and last_tested:
        is_stale = last_tested < datetime.now(timezone.utc) - timedelta(days=_STALE_ASSUMPTION_THRESHOLD_DAYS)
    emoji = _status_emoji(status, is_stale)
    confidence = assumption.get("confidence_score")
    confidence_text, low_confidence = _confidence_label(confidence)
    low_flag = " · *Low Confidence*" if low_confidence and highlight_low_confidence else ""
    owner_id = assumption.get("owner_id")
    owner_text = f" · Owner: <@{owner_id}>" if owner_id else ""
    title_text = _truncate(assumption.get("title", "Untitled"))
    return {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"{emoji} *{title_text}*\nStatus: {status} · Confidence: {confidence_text}{low_flag}{owner_text}",
        },
        "accessory": {
            "type": "overflow",
            "action_id": "assumption_overflow",
            "options": [
                {
                    "text": {"type": "plain_text", "text": "Edit"},
                    "value": f"{assumption['id']}:edit_text",
                },
                {
                    "text": {"type": "plain_text", "text": "Archive"},
                    "value": f"{assumption['id']}:archive",
                },
                {
                    "text": {"type": "plain_text", "text": "Design Test"},
                    "value": f"{assumption['id']}:design_assumption_experiment",
                },
            ],
        },
    }


def _plan_assumption_blocks(assumption: dict[str, Any]) -> list[dict[str, Any]]:
    section = _assumption_section(assumption)
    section.pop("accessory", None)
    return [
        section,
        {
            "type": "actions",
            "elements": [
                _safe_button("🗳️ Decision Room", "open_decision_vote", value=assumption["id"]),
                _safe_button("Design Test", "design_experiment", value=assumption["id"]),
            ],
        },
    ]


def _action_assumption_blocks(assumption: dict[str, Any]) -> list[dict[str, Any]]:
    section = _assumption_section(assumption)
    section.pop("accessory", None)
    return [
        section,
        {
            "type": "actions",
            "elements": [
                _safe_button(
                    "🧪 Log Experiment",
                    "log_experiment_for_assumption",
                    value=assumption["id"],
                    style="primary",
                )
            ],
        },
    ]


def _normalise_category(value: str | None) -> str:
    if value in _OCP_CATEGORIES:
        return value
    return "Opportunity"


def _normalise_horizon(value: str | None) -> str:
    if not value:
        return "now"
    lower_value = value.lower()
    if lower_value in {"now", "next", "later"}:
        return lower_value
    if value in {"Now", "Next", "Later"}:
        return value.lower()
    return "now"


def _get_current_phase(assumptions: list[dict[str, Any]]) -> str:
    def _sort_key(item: dict[str, Any]) -> float:
        value = item.get("updated_at") or item.get("last_tested_at")
        parsed = _parse_datetime(value)
        return parsed.timestamp() if parsed else 0.0

    sorted_assumptions = sorted(assumptions, key=_sort_key, reverse=True)
    for assumption in sorted_assumptions:
        phase = assumption.get("test_and_learn_phase")
        if phase:
            return str(phase).lower()
    return "define"


def _build_phase_stepper(flow_stage: str) -> dict[str, Any]:
    return {
        "type": "actions",
        "elements": [
            _safe_button(
                "1️⃣ Audit",
                "action_set_flow_stage",
                value="audit",
                style="primary" if flow_stage == "audit" else None,
            ),
            _safe_button(
                "2️⃣ Plan",
                "action_set_flow_stage",
                value="plan",
                style="primary" if flow_stage == "plan" else None,
            ),
            _safe_button(
                "3️⃣ Action",
                "action_set_flow_stage",
                value="action",
                style="primary" if flow_stage == "action" else None,
            ),
        ],
    }


def get_home_view(
    user_id: str,
    project: dict[str, Any] | None,
    all_projects: list[dict[str, Any]] | None = None,
    plan_suggestion: str | None = None,
    *,
    playbook_service: PlaybookService,
) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    assumptions = project.get("assumptions", []) if project else []
    total_assumptions = len(assumptions)
    validated_count = sum(
        1
        for assumption in assumptions
        if (assumption.get("status") or assumption.get("validation_status")) == "Validated"
    )
    health_score = int((validated_count / total_assumptions) * 100) if total_assumptions else 0
    avg_confidence = (
        int(sum((assumption.get("confidence_score") or 0) for assumption in assumptions) / total_assumptions * 20)
        if total_assumptions
        else 0
    )

    flow_stage = (project.get("flow_stage") or "audit").lower() if project else "audit"
    flow_label = _FLOW_STAGE_LABELS.get(flow_stage, "Audit")

    all_projects = all_projects or []
    if project and not any(item.get("id") == project.get("id") for item in all_projects):
        all_projects = [*all_projects, {"name": project["name"], "id": project["id"]}]
    if all_projects:
        project_options = [
            {
                "text": {
                    "type": "plain_text",
                    "text": (
                        item["name"][: _MAX_PROJECT_NAME_LENGTH_SLACK_UI - 3] + "..."
                        if len(item["name"]) > _MAX_PROJECT_NAME_LENGTH_SLACK_UI
                        else item["name"]
                    ),
                },
                "value": str(item["id"]),
            }
            for item in all_projects
        ]
        initial_option = next(
            (option for option in project_options if option["value"] == str(project["id"])),
            None,
        )
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Active Project:*"},
                "accessory": {
                    "type": "static_select",
                    "placeholder": {"type": "plain_text", "text": "Select Project"},
                    "options": project_options,
                    "initial_option": initial_option,
                    "action_id": "select_active_project",
                },
            }
        )
    else:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Active Project:* _None selected_"}})

    action_elements = [
        _safe_button("➕ New Project", "open_new_project_modal", style="primary"),
    ]
    if project:
        action_elements.append(_safe_button("🔗 Link Channel", "open_link_channel"))
        action_elements.append(_safe_button("📅 Generate Meeting Agenda", "generate_meeting_agenda"))
        action_elements.append(_safe_button("📄 Export Strategy Doc", "export_strategy_doc"))
    blocks.append({"type": "actions", "elements": action_elements})

    if project:
        channel_text = (
            f"Currently linked to channel: <#{project.get('channel_id')}>"
            if project.get("channel_id")
            else "Currently linked to channel: _Not linked_"
        )
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": channel_text}],
            }
        )
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Innovation Score:* {UIManager._progress_bar(avg_confidence)}",
                },
            }
        )

    if not project:
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "Select a project to begin the Audit → Plan → Action journey."},
            }
        )
        return {"type": "home", "blocks": blocks}

    blocks.extend(
        [
            {"type": "divider"},
            _build_phase_stepper(flow_stage),
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{project.get('name', 'Project')} · {flow_label}"},
            },
        ]
    )

    if flow_stage == "audit":
        blocks.extend(
            [
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"*OCP Dashboard* · Health Score: {health_score}% ({validated_count}/{total_assumptions} validated)",
                        }
                    ],
                },
                {
                    "type": "actions",
                    "elements": [
                        _safe_button("📝 Run Diagnostic", "action_open_diagnostic", style="primary"),
                        _safe_button("➕ Add Assumption", "open_add_assumption"),
                        _safe_button("🔄 Refresh", "refresh_home"),
                    ],
                },
                {"type": "divider"},
            ]
        )

        for category in _OCP_CATEGORIES:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*{category}*"},
                }
            )
            category_items = [
                assumption
                for assumption in assumptions
                if _normalise_category(assumption.get("category")) == category
            ]
            if not category_items:
                blocks.append(
                    {
                        "type": "context",
                        "elements": [{"type": "mrkdwn", "text": "_No assumptions yet._"}],
                    }
                )
            else:
                blocks.extend(_assumption_section(item, highlight_low_confidence=True) for item in category_items)
            blocks.append({"type": "divider"})

    elif flow_stage == "plan":
        blocks.extend(
            [
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "*Iterative Scaling Roadmap* · Move assumptions across horizons.",
                        }
                    ],
                },
                {
                    "type": "actions",
                    "elements": [
                        _safe_button("📍 Update Roadmap", "open_roadmap_modal", style="primary"),
                        _safe_button("➕ Add Assumption", "open_add_assumption"),
                        _safe_button("🔄 Refresh", "refresh_home"),
                    ],
                },
                {"type": "divider"},
            ]
        )
        if plan_suggestion:
            blocks.append(
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": plan_suggestion}],
                }
            )
            blocks.append({"type": "divider"})

        assumptions_by_horizon: dict[str, list[dict[str, Any]]] = {"now": [], "next": [], "later": []}
        for assumption in assumptions:
            horizon = _normalise_horizon(assumption.get("horizon") or assumption.get("lane"))
            assumptions_by_horizon.setdefault(horizon, []).append(assumption)

        for horizon in playbook_service.get_roadmap_horizons():
            horizon_key = horizon["key"]
            horizon_label = horizon["label"]
            horizon_hint = horizon["description"]
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{horizon_label}* · {horizon_hint}",
                    },
                }
            )
            horizon_items = assumptions_by_horizon.get(horizon_key, [])
            if not horizon_items:
                blocks.append(
                    {
                        "type": "context",
                        "elements": [{"type": "mrkdwn", "text": "_No assumptions in this horizon._"}],
                    }
                )
            else:
                for item in horizon_items:
                    blocks.extend(_plan_assumption_blocks(item))
            blocks.append({"type": "divider"})

    else:
        current_phase_key = _get_current_phase(assumptions)
        phase = playbook_service.get_phase_details(current_phase_key)
        activities = phase.get("activities", [])
        activities_text = (
            "\n".join(f"• {activity}" for activity in activities) if activities else "• Activities coming soon."
        )
        phase_index = next(
            (
                index
                for index, item in enumerate(playbook_service.get_test_and_learn_phases(), start=1)
                if item["key"] == current_phase_key
            ),
            1,
        )

        blocks.extend(
            [
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "*Test & Learn Playbook* · Execute experiments aligned to your roadmap.",
                        }
                    ],
                },
                {
                    "type": "actions",
                    "elements": [
                        _safe_button("🧪 Log Experiment", "open_create_experiment_modal", style="primary"),
                        _safe_button("📖 View Playbook Methods", "view_playbook_methods"),
                        _safe_button("🔄 Refresh", "refresh_home"),
                    ],
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Current Test & Learn Phase:* Phase {phase_index} · {phase['label']}",
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{phase['label']}* — {phase['title']}\n*Key Team Activities*\n{activities_text}",
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "_Methodology map placeholder: Define → Shape Systems → Develop → Test & Learn → Diffuse._",
                    },
                },
                {"type": "divider"},
                {"type": "section", "text": {"type": "mrkdwn", "text": "*Assumptions ready for action*"}},
            ]
        )
        for assumption in assumptions:
            blocks.extend(_action_assumption_blocks(assumption))
            blocks.append({"type": "divider"})

    integrations = project.get("integrations") or {}
    drive_info = integrations.get("drive") or {}
    connected_files = drive_info.get("files") or []

    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*📂 Project Context & Evidence*"}})
    if connected_files:
        for file_item in connected_files:
            name = _truncate(file_item.get("name", "Untitled file"))
            mime_type = file_item.get("mime_type", "")
            emoji = "📊" if "spreadsheet" in mime_type else "📄"
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"{emoji} {name}"},
                    "accessory": _safe_button("Remove", "remove_drive_file", value=file_item.get("id")),
                }
            )
        blocks.append(
            {
                "type": "actions",
                "elements": [_safe_button("✨ Auto-Fill from Evidence", "auto_fill_from_evidence", style="primary")],
            }
        )
    else:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "_No connected files yet._"}],
            }
        )

    return {"type": "home", "blocks": blocks}
