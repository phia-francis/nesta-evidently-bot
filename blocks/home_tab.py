import logging
from typing import Iterable, List

from config import Brand
from services.chart_service import ChartService

logger = logging.getLogger(__name__)

_WORKSPACES = [
    ("overview", "🏠 Overview"),
    ("discovery", "💡 Discovery"),
    ("roadmap", "🗺️ Roadmap"),
    ("experiments", "⚗️ Experiments"),
    ("team", "👥 Team"),
]

FALLBACK_CHART_URL = "https://via.placeholder.com/300?text=Evidently"


def _navigation_block(current_workspace: str) -> dict:
    """Persistent navigation for the 5-workspace model."""
    buttons = []
    for workspace, label in _WORKSPACES:
        button: dict = {
            "type": "button",
            "text": {"type": "plain_text", "text": label},
            "action_id": "navigate_workspace",
            "value": workspace,
        }
        if workspace == current_workspace:
            button["style"] = "primary"
        buttons.append(button)
    return {"type": "actions", "elements": buttons}


def _next_step_footer(text: str) -> dict:
    return {
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"➡️ *Next step:* {text}"},
    }


def _ai_suggestion_block(suggestion: dict) -> List[dict]:
    confidence = suggestion.get("confidence_score") or suggestion.get("confidence") or 0
    provenance = suggestion.get("provenance_source", "Unknown source")
    source_id = suggestion.get("source_id", "")
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": suggestion.get("text", "AI suggestion pending.")},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"🤖 Confidence: {confidence}% | Source: {provenance}{f' ({source_id})' if source_id else ''}",
                }
            ],
        },
    ]


def render_overview_workspace(user_id: str, project_data: dict) -> List[dict]:
    assumptions = project_data.get("assumptions", [])
    progress_score = project_data.get("progress_score") or _calculate_average_confidence(assumptions)

    try:
        chart_url = ChartService.generate_progress_ring(progress_score, "Confidence")
    except Exception as exc:  # noqa: BLE001
        logger.error("Chart generation failed: %s", exc)
        chart_url = FALLBACK_CHART_URL

    blocks: List[dict] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"👋 *Welcome, <@{user_id}>.*\n"
                    f"Project: *{project_data.get('name', 'Evidence Backlog')}*\n"
                    f"Phase: *{project_data.get('phase', 'Discovery')}*\n"
                    f"Average confidence: *{progress_score}%*"
                ),
            },
            "accessory": {
                "type": "image",
                "image_url": chart_url,
                "alt_text": "Confidence ring",
            },
        },
        {"type": "divider"},
        {"type": "header", "text": {"type": "plain_text", "text": "Inbox • AI suggestions"}},
    ]

    ai_suggestions = project_data.get("ai_suggestions") or []
    if not ai_suggestions:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "_No new AI insights yet._"}})
    else:
        for suggestion in ai_suggestions:
            blocks.extend(_ai_suggestion_block(suggestion))

    blocks.append(_next_step_footer("Review the AI inbox and prioritise one item for discovery."))
    return blocks


def render_discovery_workspace(project_data: dict) -> List[dict]:
    assumptions = project_data.get("assumptions", [])
    blocks: List[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": "OCP Canvas"}},
    ]

    canvas = [
        ("🟡 Opportunity", "Do users truly value this?", "opportunity"),
        ("🟢 Capability", "Can we deliver it reliably?", "capability"),
        ("🔵 Progress", "Is the solution sustainable?", "progress"),
    ]
    for label, prompt, key in canvas:
        matching = [a for a in assumptions if a.get("category") == key]
        detail = matching[0].get("text") if matching else prompt
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{label}*\n{detail}"},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Add Assumption"},
                    "action_id": "open_new_assumption_modal",
                    "value": key,
                },
            }
        )

    blocks.append(_next_step_footer("Capture at least one assumption per lane to unblock research."))
    return blocks


def render_roadmap_workspace(project_data: dict) -> List[dict]:
    roadmap = project_data.get("roadmap", {"now": [], "next": [], "later": []})
    blocks: List[dict] = [{"type": "header", "text": {"type": "plain_text", "text": "Now / Next / Later"}}]

    for lane_key, lane_label in ("now", "Now"), ("next", "Next"), ("later", "Later"):
        items = roadmap.get(lane_key) or []
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"*{lane_label}*"}]})
        if not items:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "_No items yet._"}})
        for item in items:
            text = item.get("text", "Untitled item") if isinstance(item, dict) else str(item)
            value = item.get("id", text) if isinstance(item, dict) else text
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"• {text}"},
                    "accessory": {
                        "type": "overflow",
                        "action_id": "roadmap_overflow",
                        "options": [
                            {
                                "text": {"type": "plain_text", "text": "Move to Next"},
                                "value": f"move_next::{value}",
                            },
                            {
                                "text": {"type": "plain_text", "text": "Move to Later"},
                                "value": f"move_later::{value}",
                            },
                        ],
                    },
                }
            )

    blocks.append(_next_step_footer("Prioritise one Now item to advance this week."))
    return blocks


def render_experiments_workspace(project_data: dict) -> List[dict]:
    experiments = project_data.get("experiments", [])
    blocks: List[dict] = [{"type": "header", "text": {"type": "plain_text", "text": "Active Experiments"}}]
    if not experiments:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "_No experiments running yet._"}})
    for exp in experiments:
        current = exp.get("current_metric", 0)
        target = exp.get("target_metric", 0)
        status_emoji = "🟢" if current >= target else "🟡" if current >= target * 0.8 else "🔴"
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*{exp.get('name', 'Experiment')}* {status_emoji}\n"
                        f"Metric: {exp.get('metric', 'Metric')}\n"
                        f"Current: {current} / Target: {target}"
                    ),
                },
            }
        )
        if status_emoji == "🔴":
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Alert:* Off-track result. Investigate immediately.",
                    },
                }
            )

    blocks.append(_next_step_footer("Review any red signals and agree the next intervention."))
    return blocks


def render_team_workspace() -> List[dict]:
    blocks: List[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": "Decision Room"}},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "Run a quick consensus scoring session."},
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "Start Decision Session"},
                "action_id": "start_decision_session",
                "value": "start",
                "style": "primary",
            },
        },
    ]
    blocks.append(_next_step_footer("Invite the team to score the riskiest assumption."))
    return blocks


def _calculate_average_confidence(assumptions: Iterable[dict]) -> int:
    active_scores = [a.get("confidence_score", a.get("confidence", 0)) for a in assumptions if a.get("status") != "archived"]
    if not active_scores:
        return 0
    return round(sum(active_scores) / len(active_scores))


def get_home_view(user_id: str, project_data: dict, current_workspace: str) -> dict:
    blocks: List[dict] = [_navigation_block(current_workspace), {"type": "divider"}]

    if current_workspace == "discovery":
        blocks.extend(render_discovery_workspace(project_data))
    elif current_workspace == "roadmap":
        blocks.extend(render_roadmap_workspace(project_data))
    elif current_workspace == "experiments":
        blocks.extend(render_experiments_workspace(project_data))
    elif current_workspace == "team":
        blocks.extend(render_team_workspace())
    else:
        blocks.extend(render_overview_workspace(user_id, project_data))

    blocks.append(
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "Powered by *Evidently* · Nesta Test & Learn"},
                {"type": "mrkdwn", "text": f"Palette: {Brand.NESTA_NAVY} | {Brand.NESTA_TEAL}"},
            ],
        }
    )

    return {"type": "home", "blocks": blocks}
