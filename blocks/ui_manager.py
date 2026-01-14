from typing import Any

from blocks.ui_strings import DEFAULT_STAGE_DESCRIPTION, DISCOVERY_WORKSPACE_TITLE, NAV_BUTTONS


class UIManager:
    _VELOCITY_THRESHOLDS = (
        (5, "High 🚀"),
        (2, "Moderate 🟢"),
        (0, "Low 🟠"),
    )

    @staticmethod
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

    @staticmethod
    def _nesta_header(title: str, subtitle: str) -> list[dict[str, Any]]:
        return [
            {"type": "header", "text": {"type": "plain_text", "text": title}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": subtitle}]},
            {"type": "divider"},
        ]

    @staticmethod
    def _empty_state(
        text: str,
        button_text: str,
        button_action: str,
        value: str | int | None = None,
    ) -> dict[str, Any]:
        return {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"_{text}_"},
            "accessory": UIManager._safe_button(button_text, button_action, value=value),
        }

    @staticmethod
    def _nesta_card(
        title: str,
        status_emoji: str,
        fields_dict: dict[str, str],
        button_text: str,
        action_id: str,
        value: str,
    ) -> dict[str, Any]:
        fields = [{"type": "mrkdwn", "text": f"*{label}*\n{text}"} for label, text in fields_dict.items()]
        return {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{status_emoji} {title}*"},
            "fields": fields,
            "accessory": UIManager._safe_button(button_text, action_id, value),
        }

    @staticmethod
    def get_home_view(
        user_id: str,
        project: dict[str, Any] | None,
        all_projects: list[dict[str, Any]] | None = None,
        active_tab: str = "overview",
        metrics: dict[str, int] | None = None,
        stage_info: dict[str, Any] | None = None,
        next_best_actions: list[str] | None = None,
        experiment_page: int = 0,
    ) -> dict:
        if not project:
            return UIManager._get_onboarding_view()

        metrics = metrics or {"experiments": 0, "validated": 0, "rejected": 0}
        stage_info = stage_info or {
            "desc": DEFAULT_STAGE_DESCRIPTION,
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
        blocks.append(
            {
                "type": "actions",
                "elements": [UIManager._safe_button("⬅ Back to Projects", "back_to_hub")],
            }
        )
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
            blocks.extend(
                UIManager._render_overview_workspace(project, metrics, next_best_actions, experiment_page)
            )
        elif workspace == "discovery":
            blocks.extend(UIManager._render_discovery_workspace(project, subtab, metrics))
        elif workspace == "roadmap":
            blocks.extend(UIManager._render_roadmap_workspace(project))
        elif workspace == "experiments":
            blocks.extend(UIManager._render_experiments_workspace(project))
        elif workspace == "team":
            blocks.extend(UIManager._render_team_workspace(project, subtab))
        elif workspace == "help":
            blocks.extend(UIManager._render_help_workspace())

        blocks.append(
            {
                "type": "actions",
                "elements": [
                    UIManager._safe_button("➕ New Project", "setup_step_1"),
                    UIManager._safe_button("⚡ Quick Create", "open_create_project_modal"),
                ],
            }
        )

        return {"type": "home", "blocks": blocks}

    @staticmethod
    def _nav_buttons(active_tab: str) -> list[dict[str, Any]]:
        buttons = []
        workspace, _ = UIManager._parse_tab(active_tab)
        for label, value, action_id in NAV_BUTTONS:
            button = UIManager._safe_button(label, action_id, value=value)
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
        experiment_page: int,
    ) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Project Health & Metrics*"}})
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "Last updated: just now"}],
            }
        )
        confidence_score = int(project.get("confidence_score", 0))
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Project Score:*\n{UIManager._progress_bar(confidence_score)}"},
            }
        )
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

        experiments = project.get("experiments", [])
        active_experiments = [exp for exp in experiments if exp.get("status") not in {"Completed", "Archived"}]
        completed_experiments = [exp for exp in experiments if exp.get("status") in {"Completed", "Archived"}]
        blocks.append({"type": "header", "text": {"type": "plain_text", "text": "🧪 Experiments"}})

        page_size = 5
        total_pages = max(1, (len(active_experiments) + page_size - 1) // page_size)
        page = max(0, min(experiment_page, total_pages - 1))
        start = page * page_size
        end = start + page_size
        paged_experiments = active_experiments[start:end]

        if paged_experiments:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Active*"}})
            for experiment in paged_experiments:
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*{experiment.get('title', 'Untitled')}* — {experiment.get('status', 'Planning')}",
                        },
                        "accessory": {
                            "type": "overflow",
                            "action_id": "experiment_overflow",
                            "options": [
                                {
                                    "text": {"type": "plain_text", "text": "Edit"},
                                    "value": f"edit:{experiment['id']}",
                                },
                                {
                                    "text": {"type": "plain_text", "text": "Archive"},
                                    "value": f"archive:{experiment['id']}",
                                },
                                {
                                    "text": {"type": "plain_text", "text": "Sync to Asana"},
                                    "value": f"sync:{experiment['id']}",
                                },
                            ],
                        },
                    }
                )
                blocks.append(
                    {
                        "type": "actions",
                        "elements": [
                            UIManager._safe_button(
                                "Delete Experiment",
                                "delete_experiment",
                                value=experiment["id"],
                                style="danger",
                            )
                        ],
                    }
                )
        else:
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "No active experiments yet."}]})

        if completed_experiments:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Completed*"}})
            for experiment in completed_experiments[:3]:
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"✅ {experiment.get('title', 'Untitled')} ({experiment.get('status', 'Completed')})",
                        },
                    }
                )
        if total_pages > 1:
            prev_button = UIManager._safe_button(
                "Previous",
                "experiments_page_prev",
                value=page - 1,
                style="primary" if page > 0 else None,
            )
            next_button = UIManager._safe_button(
                "Next",
                "experiments_page_next",
                value=page + 1,
                style="primary" if page < total_pages - 1 else None,
            )
            blocks.append(
                {
                    "type": "actions",
                    "elements": [prev_button, next_button],
                }
            )
        blocks.append(
            {"type": "context", "elements": [{"type": "mrkdwn", "text": "View all experiments in the Experiments tab."}]}
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
    def _progress_bar(score: int) -> str:
        blocks = 5
        filled = min(blocks, max(0, round(score / 20)))
        return "🟩" * filled + "⬜" * (blocks - filled)

    @staticmethod
    def _render_discovery_workspace(
        project: dict[str, Any],
        subtab: str,
        metrics: dict[str, int],
    ) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": DISCOVERY_WORKSPACE_TITLE}})
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    UIManager._safe_button(
                        "Canvas",
                        "tab_discovery_canvas",
                        value="discovery:canvas",
                        style="primary" if subtab in ("", "canvas") else None,
                    ),
                    UIManager._safe_button(
                        "Insights",
                        "tab_discovery_insights",
                        value="discovery:insights",
                        style="primary" if subtab == "insights" else None,
                    ),
                    UIManager._safe_button(
                        "Question banks",
                        "tab_discovery_questions",
                        value="discovery:questions",
                        style="primary" if subtab == "questions" else None,
                    ),
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
                    "elements": [UIManager._safe_button("Attach scorecard", "attach_question_bank")],
                }
            )
        return blocks

    @staticmethod
    def _render_roadmap_workspace(project: dict[str, Any]) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        project_id = project.get("id")
        blocks.extend(UIManager._nesta_header("🗺️ Strategic Roadmap", "Track what needs to be true for success."))
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    UIManager._safe_button("✨ Magic Import", "open_magic_import_modal", project_id),
                    UIManager._safe_button(
                        "➕ New Assumption",
                        "open_create_assumption_modal",
                        project_id,
                        "primary",
                    ),
                ],
            }
        )
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "Paste text to auto-extract."}],
            }
        )
        blocks.append({"type": "divider"})

        assumptions = project.get("assumptions", [])
        if not assumptions:
            blocks.append(
                UIManager._empty_state(
                    "No assumptions mapped. Import from a doc or add one manually.",
                    "✨ Magic Import",
                    "open_magic_import_modal",
                    project_id,
                )
            )
            return blocks

        for assumption in assumptions:
            title = assumption.get("title", "Untitled")
            lane = assumption.get("lane", "Now")
            density = assumption.get("evidence_density", 0)
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*{title}*"},
                    "accessory": {
                        "type": "overflow",
                        "action_id": "assumption_overflow",
                        "options": [
                            {"text": {"type": "plain_text", "text": "Edit"}, "value": f"{assumption['id']}:edit_text"},
                            {"text": {"type": "plain_text", "text": "Move"}, "value": f"{assumption['id']}:move"},
                            {"text": {"type": "plain_text", "text": "Delete"}, "value": f"{assumption['id']}:delete"},
                        ],
                    },
                }
            )
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"Lane: {lane} • Evidence: {density} docs"},
                    ],
                }
            )
            blocks.append({"type": "divider"})
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
                        UIManager._safe_button("Add Item", "add_canvas_item", value=section),
                        UIManager._safe_button("✨ AI Auto-fill", "ai_autofill_canvas", value=section),
                    ],
                }
            )
            blocks.append({"type": "divider"})
        return blocks

    @staticmethod
    def _render_experiments_workspace(project: dict[str, Any]) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        project_id = project.get("id")
        blocks.extend(
            UIManager._nesta_header(
                "🧪 Experiment Lab",
                "Design tests to validate your risky assumptions.",
            )
        )
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    UIManager._safe_button(
                        "➕ New Experiment",
                        "open_create_experiment_modal",
                        project_id,
                        "primary",
                    )
                ],
            }
        )
        blocks.append({"type": "divider"})

        experiments = project.get("experiments", [])
        if not experiments:
            blocks.append(
                UIManager._empty_state(
                    "No active tests. Create a hypothesis to start learning.",
                    "Create Experiment",
                    "open_create_experiment_modal",
                    project_id,
                )
            )
            return blocks

        for experiment in experiments:
            status = experiment.get("status", "Planning")
            primary_kpi = experiment.get("primary_kpi", "—")
            method = experiment.get("method", "—")
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"🧪 *{experiment.get('title', 'Untitled')}* ({status})\n"
                            f"KPI: {primary_kpi} | Method: {method}"
                        ),
                    },
                }
            )
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        UIManager._safe_button(
                            "Delete",
                            "delete_experiment",
                            value=experiment["id"],
                            style="danger",
                        )
                    ],
                }
            )
            blocks.append({"type": "divider"})
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
                    UIManager._safe_button("🔍 Extract Insights (Manual)", "open_extract_insights"),
                    UIManager._safe_button("📄 Generate Learning Report (PDF)", "export_report", value="pdf"),
                    UIManager._safe_button("💾 Export CSV", "export_report", value="csv"),
                    UIManager._safe_button("📢 Broadcast Update", "broadcast_update"),
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
        project_id = project.get("id")
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Team workspace*"}})
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    UIManager._safe_button(
                        "Decision Room",
                        "tab_team_decision",
                        value="team:decision",
                        style="primary" if subtab in ("", "decision") else None,
                    ),
                    UIManager._safe_button(
                        "Integrations",
                        "tab_team_integrations",
                        value="team:integrations",
                        style="primary" if subtab == "integrations" else None,
                    ),
                    UIManager._safe_button(
                        "Automation",
                        "tab_team_automation",
                        value="team:automation",
                        style="primary" if subtab == "automation" else None,
                    ),
                ],
            }
        )
        blocks.append({"type": "divider"})

        members = project.get("members", [])
        member_count = len(members)
        if members:
            member_lines = []
            for member in members:
                user_id = member.get("user_id", "unknown")
                role = member.get("role", "member")
                member_lines.append(f"• <@{user_id}> ({role})")
            members_text = "\n".join(member_lines)
        else:
            members_text = "_No team members yet._"

        blocks.append({"type": "header", "text": {"type": "plain_text", "text": "👤 Team Management"}})
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Members ({member_count}):*\n{members_text}"},
                "accessory": UIManager._safe_button("Invite Member", "open_invite_member"),
            }
        )
        blocks.append({"type": "divider"})

        blocks.append({"type": "header", "text": {"type": "plain_text", "text": "🔌 Integrations"}})
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": "Connect tools to let AI read your evidence automatically."}
                ],
            }
        )
        integrations = project.get("integrations") or {}
        drive_connected = integrations.get("drive", {}).get("connected")
        drive_status = "🟢 Connected" if drive_connected else "⚪ Not connected"
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Google Drive*\nStatus: {drive_status}"},
                "accessory": UIManager._safe_button(
                    "Connect Google Drive",
                    "start_google_auth",
                    project_id,
                    "primary" if not drive_connected else None,
                ),
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
                    "elements": [UIManager._safe_button("Open Decision Room", "trigger_decision_room")],
                }
            )
        elif subtab == "automation":
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
                    "accessory": UIManager._safe_button("+ New Rule", "create_automation_modal"),
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

        channel_id = project.get("channel_id")
        channel_text = f"Linked channel: <#{channel_id}>" if channel_id else "No channel linked yet."
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Slack Channel*\n" + channel_text},
            }
        )
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    UIManager._safe_button("Link Existing Channel", "open_link_channel"),
                    UIManager._safe_button("Create New Channel", "open_create_channel"),
                ],
            }
        )

        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*⚠️ Danger Zone*"}})
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    UIManager._safe_button("Archive Project", "archive_project"),
                    UIManager._safe_button("Delete Project", "delete_project_confirm", style="danger"),
                ],
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
                    "text": "*1. Setup*\nCreate a project from the Home tab and link a channel for team updates.",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*2. The Roadmap (Now/Next/Later)*\nAdd assumptions you want to test and prioritize them by lane.",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*3. The Toolkit*\nUse the Experiments tab to design tests. The AI can suggest methods based on your canvas.",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*4. Insights*\nUse the Extract Insights shortcut on any thread to capture evidence.",
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
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "Welcome! Let's set up your first mission."},
                },
                {
                    "type": "actions",
                    "elements": [UIManager._safe_button("➕ New Project", "setup_step_1", style="primary")],
                },
            ],
        }

    @staticmethod
    def render_project_hub(
        projects: list[dict[str, Any]],
        user_id: str,
        admin_user_id: str | None = None,
    ) -> dict:
        blocks: list[dict[str, Any]] = []
        blocks.extend(UIManager._nesta_header("🏛️ Discovery Hub", "Manage your innovation missions."))
        blocks.append(
            {
                "type": "actions",
                "elements": [UIManager._safe_button("➕ Start New Mission", "open_create_project_modal", style="primary")],
            }
        )
        if not projects:
            blocks.append(
                UIManager._empty_state(
                    "You aren't tracking any missions yet.",
                    "Start First Mission",
                    "open_create_project_modal",
                )
            )
            if admin_user_id and user_id == admin_user_id:
                blocks.append({"type": "divider"})
                blocks.append(
                    {
                        "type": "actions",
                        "elements": [UIManager._safe_button("🔐 Admin Dashboard", "open_admin_dashboard")],
                    }
                )
            return {"type": "home", "blocks": blocks}

        for project in projects:
            stage = (project.get("stage") or "Define").lower()
            status_emoji = {"define": "⚪", "develop": "🔵", "deliver": "🟢"}.get(stage, "⚪")
            mission = project.get("mission") or "Mission not set"
            channel_text = f"<#{project['channel_id']}>" if project.get("channel_id") else "No channel linked"
            blocks.append(
                UIManager._nesta_card(
                    title=project["name"],
                    status_emoji=status_emoji,
                    fields_dict={"Mission": mission, "Channel": channel_text},
                    button_text="Open Dashboard",
                    action_id="open_project_dashboard",
                    value=str(project["id"]),
                )
            )
            blocks.append({"type": "divider"})
        if admin_user_id and user_id == admin_user_id:
            blocks.append({"type": "divider"})
            blocks.append(
                {
                    "type": "actions",
                    "elements": [UIManager._safe_button("🔐 Admin Dashboard", "open_admin_dashboard")],
                }
            )
        return {"type": "home", "blocks": blocks}

    @staticmethod
    def render_admin_dashboard(all_projects: list[dict[str, Any]]) -> dict:
        total_projects = len(all_projects)
        empty_projects = [project for project in all_projects if project.get("member_count", 0) == 0]

        blocks: list[dict[str, Any]] = []
        blocks.extend(UIManager._nesta_header("🔐 Super Admin Control Panel", "Manage and clean up projects."))
        blocks.append(
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Total Projects:*\n{total_projects}"},
                    {"type": "mrkdwn", "text": f"*Empty Projects:*\n{len(empty_projects)}"},
                ],
            }
        )
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Danger Zone*"}})
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    UIManager._safe_button(
                        "🗑️ Purge 0-Member Projects",
                        "admin_purge_confirm",
                        style="danger",
                    )
                ],
            }
        )
        blocks.append({"type": "divider"})
        if not all_projects:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "No projects found."},
                }
            )
            return {"type": "home", "blocks": blocks}

        for project in all_projects:
            member_count = project.get("member_count", 0)
            name = project.get("name") or "Untitled Project"
            status = project.get("status") or "unknown"
            if member_count == 0:
                title_text = f"*⚠️ {name}*"
            else:
                title_text = f"*{name}*"
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"{title_text}\nStatus: {status} • Members: {member_count}",
                    },
                    "accessory": UIManager._safe_button(
                        "Delete",
                        "admin_delete_project",
                        value=project.get("id"),
                        style="danger",
                    ),
                }
            )
            blocks.append({"type": "divider"})
        return {"type": "home", "blocks": blocks}
