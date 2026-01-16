from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from blocks.ui_manager import UIManager


_OCP_CATEGORIES = ("Opportunity", "Capability", "Progress")
_MAX_TEXT_LENGTH = 2900
_MAX_PROJECT_NAME_LENGTH_SLACK_UI = 75
_STALE_ASSUMPTION_THRESHOLD_DAYS = 30


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


def _assumption_section(assumption: dict[str, Any]) -> dict[str, Any]:
    status = assumption.get("status") or assumption.get("validation_status") or "Testing"
    last_tested = _parse_datetime(assumption.get("last_tested_at")) or _parse_datetime(assumption.get("updated_at"))
    is_stale = False
    if status == "Testing" and last_tested:
        is_stale = last_tested < datetime.now(datetime.timezone.utc) - timedelta(days=_STALE_ASSUMPTION_THRESHOLD_DAYS)
    emoji = _status_emoji(status, is_stale)
    confidence = assumption.get("confidence_score", 0)
    owner_id = assumption.get("owner_id")
    owner_text = f" · Owner: <@{owner_id}>" if owner_id else ""
    title_text = _truncate(assumption.get("title", "Untitled"))
    return {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"{emoji} *{title_text}*\nStatus: {status} · Confidence: {confidence}%{owner_text}",
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


def _normalise_category(value: str | None) -> str:
    if value in _OCP_CATEGORIES:
        return value
    return "Opportunity"


def get_home_view(
    user_id: str,
    project: dict[str, Any] | None,
    all_projects: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not project:
        return UIManager._get_onboarding_view()

    assumptions = project.get("assumptions", [])
    total_assumptions = len(assumptions)
    validated_count = sum(
        1
        for assumption in assumptions
        if (assumption.get("status") or assumption.get("validation_status")) == "Validated"
    )
    health_score = int((validated_count / total_assumptions) * 100) if total_assumptions else 0

    integrations = project.get("integrations") or {}
    drive_info = integrations.get("drive") or {}
    connected_files = drive_info.get("files") or []

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{project.get('name', 'Project')} · OCP Dashboard"},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"*Health Score:* {health_score}% ({validated_count}/{total_assumptions} validated)",
                }
            ],
        },
        {
            "type": "actions",
            "elements": [
                _safe_button("➕ Add Assumption", "open_add_assumption", style="primary"),
                _safe_button(
                    "✨ Draft Assumption from Last Conversation",
                    "draft_assumption_from_last_convo",
                ),
                _safe_button("🔄 Refresh", "refresh_home"),
            ],
        },
        {"type": "divider"},
    ]

    all_projects = all_projects or []
    if project and not any(item.get("id") == project.get("id") for item in all_projects):
        all_projects = [*all_projects, {"name": project["name"], "id": project["id"]}]
    if all_projects:
        project_options = [
            {
                "text": {"type": "plain_text", "text": (item["name"][:_MAX_PROJECT_NAME_LENGTH_SLACK_UI - 3] + "...") if len(item["name"]) > _MAX_PROJECT_NAME_LENGTH_SLACK_UI else item["name"]},
                "value": str(item["id"]),
            }
            for item in all_projects
        ]
        initial_option = next(
            (option for option in project_options if option["value"] == str(project["id"])),
            None,
        )
        blocks.insert(
            0,
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
            },
        )

    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*📂 Connected Evidence*"}})
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
                "elements": [
                    _safe_button("✨ Auto-Fill from Evidence", "auto_fill_from_evidence", style="primary")
                ],
            }
        )
    else:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "_No connected files yet._"}],
            }
        )
    blocks.append({"type": "divider"})

    for category in _OCP_CATEGORIES:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{category}*"},
            }
        )
        category_items = [
            assumption for assumption in assumptions if _normalise_category(assumption.get("category")) == category
        ]
        if not category_items:
            blocks.append(
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": "_No assumptions yet._"}],
                }
            )
        else:
            blocks.extend(_assumption_section(item) for item in category_items)
        blocks.append({"type": "divider"})

    return {"type": "home", "blocks": blocks}
