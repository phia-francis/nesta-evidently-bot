from typing import Any, Dict, List

from blocks.nesta_ui import NestaUI


def get_home_view(project: Dict[str, Any], tip: str | None = None) -> dict:
    blocks: List[dict] = [
        NestaUI.header(f"🚀 {project['name']}"),
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Health Score:*\n{project.get('innovation_score', 0)}/100"},
                {"type": "mrkdwn", "text": f"*Velocity:*\n{project.get('velocity', 0)} exps/week"},
                {"type": "mrkdwn", "text": f"*Phase:*\n{project.get('phase', 'Discovery')}"},
            ],
        },
        NestaUI.divider(),
        NestaUI.section("*📋 Kanban Board*"),
    ]

    lanes = {"now": [], "next": [], "later": []}
    for assumption in project.get("assumptions", []):
        lane = assumption.get("lane", "later")
        if lane in lanes:
            lanes[lane].append(assumption)

    for lane_name, items in lanes.items():
        emoji = {"now": "🔥", "next": "🔭", "later": "🧊"}[lane_name]
        blocks.append(NestaUI.section(f"*{emoji} {lane_name.upper()}* ({len(items)})"))

        if not items:
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "_No items_"}]})

        for item in items:
            blocks.append(
                NestaUI.section(
                    text=(
                        f"*{item['title']}*\n"
                        f"Confidence: {item.get('confidence_score', 0)}% | "
                        f"Evidence: {item.get('evidence_score', 0)}% | "
                        f"Impact: {item.get('impact_score', 0)}%"
                    ),
                    accessory={
                        "type": "overflow",
                        "action_id": "assumption_overflow",
                        "options": [
                            {"text": {"type": "plain_text", "text": "Move to Now"}, "value": f"{item['id']}:now"},
                            {"text": {"type": "plain_text", "text": "Move to Next"}, "value": f"{item['id']}:next"},
                            {"text": {"type": "plain_text", "text": "Move to Later"}, "value": f"{item['id']}:later"},
                        ],
                    },
                )
            )
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Design Experiment"},
                            "action_id": "design_experiment",
                            "value": f"{item['id']}:{item.get('category', 'desirability')}",
                        }
                    ],
                }
            )

    blocks.append(NestaUI.divider())
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "+ Add Assumption"},
                    "action_id": "open_create_assumption",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🗳️ Decision Room"},
                    "action_id": "trigger_decision_room",
                },
            ],
        }
    )

    if tip:
        blocks.append(NestaUI.tip_panel(tip))

    return {"type": "home", "blocks": blocks}
