from typing import Any


class UIManager:
    _VELOCITY_THRESHOLDS = (
        (5, "High 🚀"),
        (2, "Moderate 🟢"),
        (0, "Low 🟠"),
    )

    @staticmethod
    def get_home_view(
        user_id: str,
        project: dict[str, Any] | None,
        all_projects: list[dict[str, Any]] | None = None,
        active_tab: str = "overview",
        metrics: dict[str, int] | None = None,
        stage_info: dict[str, Any] | None = None,
        next_best_actions: list[str] | None = None,
    ) -> dict:
        if not project:
            return UIManager._get_onboarding_view()

        metrics = metrics or {"experiments": 0, "validated": 0, "rejected": 0}
        stage_info = stage_info or {
            "desc": "Define the problem and stakeholder needs.",
            "methods": [],
            "case_study": "",
        }

        all_projects = all_projects or []
        if project and not any(item.get("id") == project.get("id") for item in all_projects):
            all_projects = [*all_projects, {"name": project["name"], "id": project["id"]}]

        project_options = [
            {
                "text": {"type": "plain_text", "text": item["name"][:75]},
                "value": str(item["id"]),
            }
            for item in all_projects
        ]
        initial_option = next(
            (option for option in project_options if option["value"] == str(project["id"])),
            None,
        )

        blocks: list[dict[str, Any]] = []
        if project_options:
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
        blocks.append(
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"🚀 {project['name']}"},
            }
        )
        blocks.append({"type": "actions", "elements": UIManager._nav_buttons(active_tab)})
        blocks.append({"type": "divider"})

        workspace, subtab = UIManager._parse_tab(active_tab)

        if workspace == "overview":
            blocks.extend(UIManager._render_overview_workspace(project, metrics, next_best_actions))
        elif workspace == "discovery":
            blocks.extend(UIManager._render_discovery_workspace(project, subtab, metrics))
        elif workspace == "roadmap":
            blocks.extend(UIManager._render_roadmap_workspace(project, subtab))
        elif workspace == "experiments":
            blocks.extend(UIManager._render_experiments_workspace(project, stage_info, subtab))
        elif workspace == "team":
            blocks.extend(UIManager._render_team_workspace(project, subtab))
        elif workspace == "help":
            blocks.extend(UIManager._render_help_workspace())

        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "➕ New Project"},
                        "action_id": "setup_step_1",
                    }
                ],
            }
        )

        return {"type": "home", "blocks": blocks}

    @staticmethod
    def _nav_buttons(active_tab: str) -> list[dict[str, Any]]:
        buttons = []
        workspace, _ = UIManager._parse_tab(active_tab)
        for label, value, action_id in [
            ("1️⃣ Overview", "overview", "nav_overview"),
            ("2️⃣ Discovery", "discovery", "nav_discovery"),
            ("3️⃣ Roadmap", "roadmap", "nav_roadmap"),
            ("4️⃣ Experiments", "experiments", "nav_experiments"),
            ("5️⃣ Team", "team", "nav_team"),
            ("❓ Help", "help", "nav_help"),
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
    def _render_overview_workspace(
        project: dict[str, Any],
        metrics: dict[str, int],
        next_best_actions: list[str] | None,
    ) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Project Health & Metrics*"}})
        blocks.append(
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Confidence Score:*\n{project.get('confidence_score', 0)}%"},
                    {"type": "mrkdwn", "text": f"*Velocity:*\n{UIManager._learning_velocity_label(metrics)}"},
                    {"type": "mrkdwn", "text": f"*Active Experiments:*\n{metrics['experiments']}"},
                    {"type": "mrkdwn", "text": f"*Key Assumptions:*\n{len(project.get('assumptions', []))}"},
                ],
            }
        )
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*✨ AI Next Best Actions*"}})
        if next_best_actions:
            actions_text = "\n".join([f"• {action}" for action in next_best_actions])
        else:
            actions_text = "No recommendations available yet."
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": actions_text,
                },
            }
        )
        return blocks

    @staticmethod
    def _render_discovery_workspace(
        project: dict[str, Any],
        subtab: str,
        metrics: dict[str, int],
    ) -> list[dict[str, Any]]:
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
                        "style": "primary" if subtab in ("", "canvas") else "default",
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
    def _render_roadmap_workspace(project: dict[str, Any], subtab: str) -> list[dict[str, Any]]:
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
                    "text": {"type": "mrkdwn", "text": "*📂 Smart Collections*"},
                    "accessory": {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "+ New Collection"},
                        "action_id": "create_collection_modal",
                    },
                }
            )
            collections = project.get("collections", [])
            if not collections:
                blocks.append(
                    {
                        "type": "context",
                        "elements": [{"type": "mrkdwn", "text": "_No collections yet._"}],
                    }
                )
            else:
                for collection in collections:
                    description = collection.get("description") or "No description"
                    blocks.append(
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"📁 *{collection['name']}*\n_{description}_",
                            },
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
    def _render_experiments_workspace(
        project: dict[str, Any],
        stage_info: dict[str, Any],
        subtab: str,
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
        velocity_label = UIManager._learning_velocity_label(metrics)
        blocks.append(
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Experiments Run:*\n{metrics['experiments']}"},
                    {"type": "mrkdwn", "text": f"*Validated Assumptions:*\n{metrics['validated']}"},
                    {"type": "mrkdwn", "text": f"*Rejected Hypotheses:*\n{metrics['rejected']}"},
                    {"type": "mrkdwn", "text": f"*Learning velocity:*\n{velocity_label}"},
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
    def _learning_velocity_label(metrics: dict[str, int]) -> str:
        experiments = metrics.get("experiments", 0)
        for threshold, label in UIManager._VELOCITY_THRESHOLDS:
            if experiments >= threshold:
                return label
        return "Low 🟠"

    @staticmethod
    def _render_team_workspace(project: dict[str, Any], subtab: str) -> list[dict[str, Any]]:
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
                    "text": {"type": "mrkdwn", "text": "*⚙️ Project Automation & Settings*"},
                }
            )
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "*⚡ Automation Rules*"},
                    "accessory": {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "+ New Rule"},
                        "action_id": "create_automation_modal",
                    },
                }
            )
            rules = project.get("automation_rules", [])
            if not rules:
                blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "_No active rules._"}]})
            else:
                for rule in rules:
                    status = "🟢 On" if rule.get("is_active") else "🔴 Off"
                    blocks.append(
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"⚡ *When {rule['trigger_event']}* → *{rule['action_type']}* ({status})",
                            },
                        }
                    )
            return blocks

        integrations = project.get("integrations") or {}
        blocks.append({"type": "header", "text": {"type": "plain_text", "text": "🔗 Integrations"}})

        drive_connected = integrations.get("drive", {}).get("connected")
        drive_status = "✅ Connected" if drive_connected else "⚪ Disconnected"
        drive_action_text = "Manage" if drive_connected else "Connect"
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Google Drive*\n{drive_status}"},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": drive_action_text},
                    "action_id": "connect_drive",
                },
            }
        )

        asana_connected = integrations.get("asana", {}).get("connected")
        asana_status = "✅ Connected" if asana_connected else "⚪ Disconnected"
        asana_action_text = "Manage" if asana_connected else "Connect"
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Asana*\n{asana_status}"},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": asana_action_text},
                    "action_id": "connect_asana",
                },
            }
        )
        return blocks

    @staticmethod
    def _render_help_workspace() -> list[dict[str, Any]]:
        return [
            {"type": "header", "text": {"type": "plain_text", "text": "📘 Evidently Instruction Manual"}},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*1. Setup*\nCreate a project from the Home tab and link a channel for team updates."
                    ),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*2. The Roadmap (Now/Next/Later)*\n"
                        "Add assumptions you want to test and prioritize them by lane."
                    ),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*3. The Toolkit*\nUse the Experiments tab to design tests. "
                        "The AI can suggest methods based on your canvas."
                    ),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*4. Insights*\nUse the Extract Insights shortcut on any thread to capture evidence."
                    ),
                },
            },
            {"type": "divider"},
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "Need more help? Contact the innovation team."}],
            },
        ]

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
