from typing import Any


class UIManager:
    @staticmethod
    def get_home_view(
        user_id: str,
        project: dict[str, Any] | None,
        active_tab: str = "overview",
        metrics: dict[str, int] | None = None,
        stage_info: dict[str, Any] | None = None,
    ) -> dict:
        if not project:
            return UIManager._get_onboarding_view()

        metrics = metrics or {"experiments": 0, "validated": 0, "rejected": 0}
        stage_info = stage_info or {
            "desc": "Define the problem and stakeholder needs.",
            "methods": [],
            "case_study": "",
        }

        blocks: list[dict[str, Any]] = []
        blocks.append(
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"🚀 {project['name']} | Stage: {project['stage']}"},
            }
        )
        blocks.append(
            {
                "type": "actions",
                "elements": UIManager._nav_buttons(active_tab),
            }
        )
        blocks.append({"type": "divider"})

        workspace, subtab = UIManager._parse_tab(active_tab)

        if workspace == "overview":
            blocks.extend(UIManager._render_overview(project, metrics))
        elif workspace == "discovery":
            blocks.extend(UIManager._render_discovery(project, subtab, metrics))
        elif workspace == "roadmap":
            blocks.extend(UIManager._render_roadmap(project, subtab))
        elif workspace == "experiments":
            blocks.extend(UIManager._render_experiments(project, stage_info, subtab))
        elif workspace == "team":
            blocks.extend(UIManager._render_team(project, subtab))

        return {"type": "home", "blocks": blocks}

    @staticmethod
    def _nav_buttons(active_tab: str) -> list[dict[str, Any]]:
        buttons = []
        workspace, _ = UIManager._parse_tab(active_tab)
        for label, value, action_id in [
            ("1️⃣ Overview", "overview", "nav_overview"),
            ("2️⃣ Discovery", "discovery:canvas", "nav_discovery"),
            ("3️⃣ Roadmap", "roadmap:roadmap", "nav_roadmap"),
            ("4️⃣ Experiments", "experiments:framework", "nav_experiments"),
            ("5️⃣ Team", "team:decision", "nav_team"),
        ]:
            button = {
                "type": "button",
                "text": {"type": "plain_text", "text": label},
                "value": value,
                "action_id": action_id,
            }
            if workspace == value.split(":", 1)[0]:
                button["style"] = "primary"
            buttons.append(button)
        return buttons

    @staticmethod
    def _parse_tab(active_tab: str) -> tuple[str, str]:
        if ":" in active_tab:
            workspace, subtab = active_tab.split(":", 1)
            return workspace, subtab
        return active_tab, ""

    @staticmethod
    def _render_overview(project: dict[str, Any], metrics: dict[str, int]) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Project command centre*"}})
        blocks.append(
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Experiments:*\n{metrics['experiments']}"},
                    {"type": "mrkdwn", "text": f"*Validated:*\n{metrics['validated']}"},
                    {"type": "mrkdwn", "text": f"*Rejected:*\n{metrics['rejected']}"},
                    {"type": "mrkdwn", "text": f"*Stage:*\n{project['stage']}"},
                ],
            }
        )
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*AI suggestions*"}})
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "• Review new canvas ideas in Discovery.\n• Move top assumptions into the Roadmap.",
                    }
                ],
            }
        )
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Quick actions*"}})
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✨ Extract insights"},
                        "action_id": "open_extract_insights",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "🗳️ Decision Room"},
                        "action_id": "trigger_decision_room",
                    },
                ],
            }
        )
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Team overview*"}})
        members = project.get("members", [])
        if not members:
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "No team members yet."}]})
        else:
            mentions = " ".join([f"<@{member['user_id']}>" for member in members[:8]])
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": mentions}]})
        return blocks

    @staticmethod
    def _render_discovery(project: dict[str, Any], subtab: str, metrics: dict[str, int]) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Discovery workspace*"}})
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Canvas"},
                        "value": "discovery:canvas",
                        "action_id": "tab_discovery_canvas",
                        "style": "primary" if subtab == "canvas" else "default",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Insights"},
                        "value": "discovery:insights",
                        "action_id": "tab_discovery_insights",
                        "style": "primary" if subtab == "insights" else "default",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Question banks"},
                        "value": "discovery:questions",
                        "action_id": "tab_discovery_questions",
                        "style": "primary" if subtab == "questions" else "default",
                    },
                ],
            }
        )
        blocks.append({"type": "divider"})

        if subtab in ("", "canvas"):
            blocks.extend(UIManager._render_canvas(project))
        elif subtab == "insights":
            blocks.extend(UIManager._render_insights(metrics))
        elif subtab == "questions":
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Question banks*\nAttach Strategyzer scorecards to guide evidence collection.",
                    },
                }
            )
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Attach scorecard"},
                            "action_id": "attach_question_bank",
                        }
                    ],
                }
            )
        return blocks

    @staticmethod
    def _render_roadmap(project: dict[str, Any], subtab: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Roadmap workspace*"}})
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Roadmap"},
                        "value": "roadmap:roadmap",
                        "action_id": "tab_roadmap_main",
                        "style": "primary" if subtab in ("", "roadmap") else "default",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Collections"},
                        "value": "roadmap:collections",
                        "action_id": "tab_roadmap_collections",
                        "style": "primary" if subtab == "collections" else "default",
                    },
                ],
            }
        )
        blocks.append({"type": "divider"})

        if subtab == "collections":
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Collections help you group assumptions by theme or team.",
                    },
                }
            )
            blocks.append(
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": "No collections yet. Create one to get started."}],
                }
            )
            return blocks

        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Project Roadmap (Now / Next / Later)*"}})

        lanes = {"Now": [], "Next": [], "Later": []}
        for assumption in project.get("assumptions", []):
            lane = assumption.get("lane", "Now")
            lanes.setdefault(lane, []).append(assumption)

        for lane, items in lanes.items():
            emoji = {"Now": "🔥", "Next": "🔭", "Later": "🧊"}.get(lane, "📌")
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*{emoji} {lane.upper()}*"}})
            if not items:
                blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "_No items_"}]})
            for item in items:
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"• {item['title']} (Density: {item.get('evidence_density', 0)} docs)",
                        },
                        "accessory": {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Edit"},
                            "value": str(item["id"]),
                            "action_id": "edit_assumption",
                        },
                    }
                )
            blocks.append({"type": "divider"})

        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "+ Add Item"},
                        "action_id": "open_add_assumption",
                    }
                ],
            }
        )
        return blocks

    @staticmethod
    def _render_canvas(project: dict[str, Any]) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Framework Canvas*"}})

        sections = ["Opportunity", "Capability", "Feasibility", "Progress"]
        for section in sections:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"📌 *{section}*"}})
            items = [item for item in project.get("canvas_items", []) if item["section"] == section]
            if not items:
                blocks.append(
                    {"type": "section", "text": {"type": "mrkdwn", "text": "_Empty. Add items or use AI Auto-fill._"}}
                )
            for item in items:
                icon = "🤖 " if item.get("ai_generated") else "• "
                blocks.append(
                    {
                        "type": "context",
                        "elements": [{"type": "mrkdwn", "text": f"{icon}{item['text']}"}],
                    }
                )

            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Add Item"},
                            "value": section,
                            "action_id": "add_canvas_item",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "✨ AI Auto-fill"},
                            "value": section,
                            "action_id": "ai_autofill_canvas",
                        },
                    ],
                }
            )
            blocks.append({"type": "divider"})
        return blocks

    @staticmethod
    def _render_experiments(
        project: dict[str, Any], stage_info: dict[str, Any], subtab: str
    ) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Experiments workspace*"}})
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Test & Learn"},
                        "value": "experiments:framework",
                        "action_id": "tab_experiments_framework",
                        "style": "primary" if subtab in ("", "framework") else "default",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Active experiments"},
                        "value": "experiments:active",
                        "action_id": "tab_experiments_active",
                        "style": "primary" if subtab == "active" else "default",
                    },
                ],
            }
        )
        blocks.append({"type": "divider"})

        if subtab == "active":
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Active Experiments*"}})
            experiments = project.get("experiments", [])
            if not experiments:
                blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "No active experiments."}]})
            else:
                for experiment in experiments:
                    blocks.append(
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": (
                                    f"🧪 *{experiment['title']}* ({experiment['status']})\n"
                                    f"KPI: {experiment.get('primary_kpi', '—')} | Method: {experiment['method']}"
                                ),
                            },
                            "accessory": {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Update"},
                                "value": str(experiment["id"]),
                                "action_id": "update_experiment",
                            },
                        }
                    )
            return blocks

        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Test & Learn Toolkit*"}})
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"Current Stage: *{project['stage']}*\n"
                        f"_Focus: {stage_info.get('desc', '')}_"
                    ),
                },
                "accessory": {"type": "button", "text": {"type": "plain_text", "text": "Change Stage"}, "action_id": "change_stage"},
            }
        )

        blocks.append({"type": "divider"})
        blocks.append({"type": "header", "text": {"type": "plain_text", "text": "Create New Experiment"}})
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "Use AI to generate experiment ideas based on your Canvas."},
            }
        )
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✨ AI Recommended Experiments"},
                        "action_id": "ai_recommend_experiments",
                        "style": "primary",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "+ Manual Entry"},
                        "action_id": "create_experiment_manual",
                    },
                ],
            }
        )
        return blocks

    @staticmethod
    def _render_insights(metrics: dict[str, int]) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        blocks.append({"type": "header", "text": {"type": "plain_text", "text": "📊 Insights & reporting"}})
        blocks.append(
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Experiments Run:*\n{metrics['experiments']}"},
                    {"type": "mrkdwn", "text": f"*Validated Assumptions:*\n{metrics['validated']}"},
                    {"type": "mrkdwn", "text": f"*Rejected Hypotheses:*\n{metrics['rejected']}"},
                    {"type": "mrkdwn", "text": "*Learning velocity:*\nHigh 🚀"},
                ],
            }
        )
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Export Data*"}})
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "📄 Generate Learning Report (PDF)"},
                        "value": "pdf",
                        "action_id": "export_report",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "💾 Export CSV"},
                        "value": "csv",
                        "action_id": "export_report",
                    },
                ],
            }
        )
        return blocks

    @staticmethod
    def _render_team(project: dict[str, Any], subtab: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Team workspace*"}})
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Decision Room"},
                        "value": "team:decision",
                        "action_id": "tab_team_decision",
                        "style": "primary" if subtab in ("", "decision") else "default",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Integrations"},
                        "value": "team:integrations",
                        "action_id": "tab_team_integrations",
                        "style": "primary" if subtab == "integrations" else "default",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Automation"},
                        "value": "team:automation",
                        "action_id": "tab_team_automation",
                        "style": "primary" if subtab == "automation" else "default",
                    },
                ],
            }
        )
        blocks.append({"type": "divider"})

        if subtab in ("", "decision"):
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Use Decision Room to prioritise assumptions with your team.",
                    },
                }
            )
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Open Decision Room"},
                            "action_id": "trigger_decision_room",
                        }
                    ],
                }
            )
            return blocks

        if subtab == "automation":
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Automation rules will help you triage AI insights automatically.",
                    },
                }
            )
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "No rules yet."}]})
            return blocks

        integrations = project.get("integrations") or {}
        blocks.append({"type": "header", "text": {"type": "plain_text", "text": "🔗 Integrations"}})

        drive_status = "✅ Connected" if integrations.get("drive", {}).get("connected") else "⚪ Disconnected"
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Google Drive*\n{drive_status}"},
                "accessory": {"type": "button", "text": {"type": "plain_text", "text": "Connect"}, "action_id": "connect_drive"},
            }
        )

        asana_status = "✅ Connected" if integrations.get("asana", {}).get("connected") else "⚪ Disconnected"
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Asana*\n{asana_status}"},
                "accessory": {"type": "button", "text": {"type": "plain_text", "text": "Connect"}, "action_id": "connect_asana"},
            }
        )
        return blocks

    @staticmethod
    def _get_onboarding_view() -> dict:
        return {
            "type": "home",
            "blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": "Please create a project first."}},
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "➕ New Project"},
                            "action_id": "setup_step_1",
                            "style": "primary",
                        }
                    ],
                },
            ],
        }
