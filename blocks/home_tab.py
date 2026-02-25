from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from blocks.ui_manager import UIManager
from constants import LOW_CONFIDENCE_THRESHOLD
from services.playbook_service import PlaybookService
from utils.diagnostic_utils import normalize_question_text


_FLOW_STAGE_LABELS = {
    "audit": "Audit",
    "plan": "Plan",
    "action": "Action",
}
_MAX_TEXT_LENGTH = 2900
_MAX_PROJECT_NAME_LENGTH_SLACK_UI = 75
_STALE_ASSUMPTION_THRESHOLD_DAYS = 30

_ROADMAP_SUMMARY_LENGTH = 120


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
    score = confidence or 0
    score = max(0, min(5, int(score)))
    stars = "⭐" * score + "☆" * (5 - score)
    is_low = 0 < score < LOW_CONFIDENCE_THRESHOLD
    return stars, is_low


def _assumption_section(assumption: dict[str, Any], highlight_low_confidence: bool = False) -> dict[str, Any]:
    status = assumption.get("status") or assumption.get("validation_status") or "Testing"
    last_tested = _parse_datetime(assumption.get("last_tested_at")) or _parse_datetime(assumption.get("updated_at"))
    is_stale = False
    if status == "Testing" and last_tested:
        is_stale = last_tested < datetime.now(timezone.utc) - timedelta(days=_STALE_ASSUMPTION_THRESHOLD_DAYS)
    emoji = _status_emoji(status, is_stale)
    confidence = assumption.get("confidence_score")
    confidence_text, low_confidence = _confidence_label(confidence)
    low_flag = " · ⚠️ Needs Evidence" if low_confidence and highlight_low_confidence else ""
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


def _plan_assumption_section(assumption: dict[str, Any]) -> dict[str, Any]:
    status = assumption.get("status") or assumption.get("validation_status") or "Testing"
    confidence = assumption.get("confidence_score")
    confidence_text, _ = _confidence_label(confidence)
    title_text = _truncate(assumption.get("title", "Untitled"))
    return {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*{title_text}*\nStatus: {status} · Confidence: {confidence_text}",
        },
        "accessory": _safe_button(
            "📍 Move",
            "move_assumption",
            value=assumption.get("id"),
        ),
    }


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


def _truncate_summary(text: str | None) -> str:
    if not text:
        return "Not set"
    if len(text) <= _ROADMAP_SUMMARY_LENGTH:
        return text
    return text[: _ROADMAP_SUMMARY_LENGTH - 3] + "..."


def _build_roadmap_snippet(plan: dict[str, Any]) -> str | None:
    plan_now = (plan.get("plan_now") or "").strip()
    plan_next = (plan.get("plan_next") or "").strip()
    plan_later = (plan.get("plan_later") or "").strip()
    if plan_now:
        return f"Now: {_truncate_summary(plan_now)}"
    if plan_next:
        return f"Next: {_truncate_summary(plan_next)}"
    if plan_later:
        return f"Later: {_truncate_summary(plan_later)}"
    return None


def _normalize_label(value: str | None) -> str:
    return (value or "").strip().lower()


def _assumption_matches(assumption: dict[str, Any], pillar: str, sub_category: str) -> bool:
    return _normalize_label(assumption.get("category")) == _normalize_label(pillar) and _normalize_label(
        assumption.get("sub_category")
    ) == _normalize_label(sub_category)


def _diagnostic_key(pillar: str, sub_category: str, question: str) -> tuple[str, str, str]:
    return (_normalize_label(pillar), _normalize_label(sub_category), normalize_question_text(question))


def _build_diagnostic_answer_lookup(assumptions: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    lookup: dict[tuple[str, str, str], dict[str, Any]] = {}
    for assumption in assumptions:
        question = assumption.get("title")
        if not question:
            continue
        key = _diagnostic_key(
            assumption.get("category"),
            assumption.get("sub_category"),
            question,
        )
        lookup[key] = assumption
    return lookup


def _should_show_sub_category(sub_data: dict | list, context_tags: list[str]) -> bool:
    """Return True if this sub-category should be shown given the project's context_tags."""
    if isinstance(sub_data, list):
        return True  # legacy list format — always show
    sub_tags = set(sub_data.get("tags", []))
    if not sub_tags:
        return True  # universal — always shown
    current_tags = set(context_tags or [])
    return bool(sub_tags.intersection(current_tags | {"universal"}))


def _get_audit_view(
    *,
    framework: dict[str, dict[str, object]],
    assumptions: list[dict[str, Any]],
    context_tags: list[str] | None = None,
    blocks: list[dict[str, Any]],
) -> None:
    current_tags = context_tags or []
    answer_lookup = _build_diagnostic_answer_lookup(assumptions)
    for pillar_key, pillar_data in framework.items():
        blocks.append(
            {
                "type": "header",
                "text": {"type": "plain_text", "text": pillar_key},
            }
        )
        sub_categories = pillar_data.get("sub_categories", {})
        for sub_category, sub_data in sub_categories.items():
            if not _should_show_sub_category(sub_data, current_tags):
                continue
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*{sub_category}*"},
                }
            )
            questions = sub_data if isinstance(sub_data, list) else sub_data.get("questions", [])
            if not questions:
                blocks.append(
                    {
                        "type": "context",
                        "elements": [{"type": "mrkdwn", "text": "_No diagnostic prompts available._"}],
                    }
                )
                continue
            for question in questions:
                lookup_key = _diagnostic_key(pillar_key, sub_category, question)
                assumption = answer_lookup.get(lookup_key, {})
                answer = assumption.get("source_snippet")
                has_answer = bool(answer)
                question_text = _truncate(question)
                if not has_answer:
                    question_text = f"_{question_text}_"
                answer_text = _truncate(answer) if has_answer else "_Diagnostic prompt — add your answer._"
                value = json.dumps({"pillar": pillar_key, "sub_category": sub_category, "question": question})
                blocks.append(
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": question_text},
                            {"type": "mrkdwn", "text": answer_text},
                        ],
                        "accessory": _safe_button(
                            "✏️ Answer",
                            "open_edit_diagnostic_answer",
                            value=value,
                        ),
                    }
                )
            blocks.append({"type": "divider"})


def _render_framework_sections(
    *,
    framework: dict[str, dict[str, object]],
    assumptions: list[dict[str, Any]],
    roadmap_plans: dict[tuple[str, str], dict[str, Any]],
    roadmap_horizons: list[dict[str, str]],
    context_tags: list[str] | None = None,
    blocks: list[dict[str, Any]],
) -> None:
    current_tags = context_tags or []
    horizon_order = [item["key"] for item in roadmap_horizons]
    horizon_labels = {item["key"]: item["label"] for item in roadmap_horizons}
    for pillar_key, pillar_data in framework.items():
        blocks.append(
            {
                "type": "header",
                "text": {"type": "plain_text", "text": pillar_key},
            }
        )
        sub_categories = pillar_data.get("sub_categories", {})
        for sub_category, sub_data in sub_categories.items():
            if not _should_show_sub_category(sub_data, current_tags):
                continue
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{sub_category}*",
                    },
                    "accessory": _safe_button(
                        "🗺️ Edit Roadmap",
                        "open_roadmap_modal",
                        value=f"{pillar_key}||{sub_category}",
                    ),
                }
            )
            plan = roadmap_plans.get((pillar_key, sub_category), {})
            plan_snippet = _build_roadmap_snippet(plan)
            if plan_snippet:
                blocks.append(
                    {
                        "type": "context",
                        "elements": [{"type": "mrkdwn", "text": plan_snippet}],
                    }
                )
            matching_assumptions = [
                assumption for assumption in assumptions if _assumption_matches(assumption, pillar_key, sub_category)
            ]
            grouped: dict[str, list[dict[str, Any]]] = {key: [] for key in horizon_order}
            for assumption in matching_assumptions:
                horizon = _normalize_label(assumption.get("horizon") or assumption.get("lane") or "now")
                horizon_key = horizon if horizon in grouped else "now"
                grouped[horizon_key].append(assumption)
            has_items = any(grouped.values())
            if has_items:
                for horizon_key in horizon_order:
                    items = grouped.get(horizon_key, [])
                    if not items:
                        continue
                    label = horizon_labels.get(horizon_key, horizon_key.upper())
                    blocks.append(
                        {
                            "type": "context",
                            "elements": [{"type": "mrkdwn", "text": f"*{label}*"}],
                        }
                    )
                    for assumption in items:
                        blocks.append(_plan_assumption_section(assumption))
            else:
                blocks.append(
                    {
                        "type": "context",
                        "elements": [{"type": "mrkdwn", "text": "_No roadmap assumptions yet._"}],
                    }
                )
            if not matching_assumptions:
                questions = sub_data if isinstance(sub_data, list) else sub_data.get("questions", [])
                prompt_text = "\n".join(questions) if questions else "No diagnostic prompts available."
                blocks.append(
                    {
                        "type": "context",
                        "elements": [{"type": "mrkdwn", "text": f"_Diagnostic prompts:_\n{prompt_text}"}],
                    }
                )
            blocks.append({"type": "divider"})


def _get_current_phase(assumptions: list[dict[str, Any]]) -> str:
    def _sort_key(item: dict[str, Any]) -> float:
        value = item.get("updated_at") or item.get("last_tested_at")
        parsed = _parse_datetime(value)
        return parsed.timestamp() if parsed else 0.0

    sorted_assumptions = sorted(assumptions, key=_sort_key, reverse=True)
    for assumption in sorted_assumptions:
        phase = assumption.get("test_phase") or assumption.get("test_and_learn_phase")
        if phase:
            normalized = str(phase).lower()
            if normalized == "diffuse":
                return "scale"
            return normalized
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
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Health Score:* {UIManager._progress_bar(health_score)}",
                },
            }
        )
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
        context_tags = project.get("context_tags") or []
        audit_action_elements = [
            _safe_button("📝 Run Diagnostic", "action_open_diagnostic", style="primary"),
            _safe_button("✨ Auto-Fill with AI", "auto_fill_from_evidence"),
            _safe_button("➕ Add Assumption", "open_add_assumption"),
            _safe_button("🔄 Refresh", "refresh_home"),
        ]
        blocks.extend(
            [
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"*5-Pillar Diagnostic* · Health Score: {health_score}% ({validated_count}/{total_assumptions} validated)",
                        }
                    ],
                },
                {
                    "type": "actions",
                    "elements": audit_action_elements,
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "⚙️ Configure Context"},
                            "action_id": "open_triage_wizard",
                            "value": str(project["id"]),
                        }
                    ],
                },
                {"type": "divider"},
            ]
        )

        framework = playbook_service.get_5_pillar_framework()
        _get_audit_view(
            framework=framework,
            assumptions=assumptions,
            context_tags=context_tags,
            blocks=blocks,
        )

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

        framework = playbook_service.get_5_pillar_framework()
        roadmap_horizons = playbook_service.get_roadmap_horizons()
        roadmap_plans = {
            (plan.get("pillar"), plan.get("sub_category")): plan for plan in project.get("roadmap_plans", [])
        }
        _render_framework_sections(
            framework=framework,
            assumptions=assumptions,
            roadmap_plans=roadmap_plans,
            roadmap_horizons=roadmap_horizons,
            context_tags=project.get("context_tags") or [],
            blocks=blocks,
        )

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
                        "text": "_Methodology map: Define → Shape Systems → Develop → Test & Learn → Scale._",
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
