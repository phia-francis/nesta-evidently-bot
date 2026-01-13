from typing import Any

from blocks.ui_strings import DEFAULT_STAGE_DESCRIPTION, DISCOVERY_WORKSPACE_TITLE, NAV_BUTTONS


class UIManager:
    _VELOCITY_THRESHOLDS = (
        (5, "High 🚀"),
        (2, "Moderate 🟢"),
        (0, "Low 🟠"),
    )

    @staticmethod
    def _nesta_header(title: str, subtitle: str) -> list[dict[str, Any]]:
        return [
            {"type": "header", "text": {"type": "plain_text", "text": title}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": subtitle}]},
            {"type": "divider"},
        ]

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
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": button_text},
                "action_id": action_id,
                "value": value,
            },
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
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "⬅ Back to Projects"},
                        "action_id": "back_to_hub",
                    }
                ],
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
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "⚡ Quick Create"},
                        "action_id": "open_create_project_modal",
                    },
                ],
            }
        )

        return {"type": "home", "blocks": blocks}

    @staticmethod
    def _nav_buttons(active_tab: str) -> list[dict[str, Any]]:
        buttons = []
        workspace, _ = UIManager._parse_tab(active_tab)
        for label, value, action_id in NAV_BUTTONS:
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
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Delete Experiment"},
                                "action_id": "delete_experiment",
                                "style": "danger",
                                "value": str(experiment["id"]),
                            }
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
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Previous"},
                            "action_id": "experiments_page_prev",
                            "value": str(page - 1),
                            "style": "primary" if page > 0 else "default",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Next"},
                            "action_id": "experiments_page_next",
                            "value": str(page + 1),
                            "style": "primary" if page < total_pages - 1 else "default",
                        },
                    ],
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
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "📄 Import from Drive"},
                        "action_id": "open_drive_import_modal",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✨ Magic Paste (Miro/Asana)"},
                        "action_id": "open_magic_paste_modal",
                    },
                ],
            }
        )

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
                    }
                )
                blocks.append(
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Edit"},
                                "action_id": "edit_assumption",
                                "value": str(item["id"]),
                            },
                            {
                                "type": "overflow",
                                "action_id": "assumption_overflow",
                                "options": [
                                    {"text": {"type": "plain_text", "text": "Move to Now"}, "value": f"{item['id']}:Now"},
                                    {"text": {"type": "plain_text", "text": "Move to Next"}, "value": f"{item['id']}:Next"},
                                    {"text": {"type": "plain_text", "text": "Move to Later"}, "value": f"{item['id']}:Later"},
                                    {"text": {"type": "plain_text", "text": "Edit Text"}, "value": f"{item['id']}:edit_text"},
                                    {
                                        "text": {"type": "plain_text", "text": "Design Experiment"},
                                        "value": f"{item['id']}:exp",
                                    },
                                    {"text": {"type": "plain_text", "text": "Delete"}, "value": f"{item['id']}:delete"},
                                ],
                            },
                        ],
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
                                {
                                    "type": "button",
                                    "text": {"type": "plain_text", "text": "Delete Experiment"},
                                    "action_id": "delete_experiment",
                                    "style": "danger",
                                    "value": str(experiment["id"]),
                                }
                            ],
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
                        "text": {"type": "plain_text", "text": "🔍 Extract Insights (Manual)"},
                        "action_id": "open_extract_insights",
                    },
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
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "📢 Broadcast Update"},
                        "action_id": "broadcast_update",
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
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Invite Member"},
                    "action_id": "open_invite_member",
                },
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
        else:
            integrations = project.get("integrations") or {}
            blocks.append({"type": "header", "text": {"type": "plain_text", "text": "🔌 Integrations"}})

            drive_connected = integrations.get("drive", {}).get("connected")
            drive_status = "🟢 Connected" if drive_connected else "⚪ Not Connected"
            blocks.append(
                UIManager._nesta_card(
                    title="Google Drive",
                    status_emoji="📁",
                    fields_dict={"Status": drive_status},
                    button_text="Configure",
                    action_id="open_integration_modal_drive",
                    value="drive",
                )
            )
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Connect Google Drive"},
                            "action_id": "connect_google_drive",
                            "style": "primary" if not drive_connected else "default",
                        }
                    ],
                }
            )

            asana_connected = integrations.get("asana", {}).get("connected")
            asana_status = "🟢 Connected" if asana_connected else "⚪ Not Connected"
            blocks.append(
                UIManager._nesta_card(
                    title="Asana",
                    status_emoji="📋",
                    fields_dict={"Status": asana_status},
                    button_text="Configure",
                    action_id="open_integration_modal_asana",
                    value="asana",
                )
            )

            miro_connected = integrations.get("miro", {}).get("connected")
            miro_status = "🟢 Connected" if miro_connected else "⚪ Not Connected"
            blocks.append(
                UIManager._nesta_card(
                    title="Miro",
                    status_emoji="🧩",
                    fields_dict={"Status": miro_status},
                    button_text="Configure",
                    action_id="open_integration_modal_miro",
                    value="miro",
                )
            )
            blocks.append({"type": "divider"})
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
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Link Existing Channel"},
                            "action_id": "open_link_channel",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Create New Channel"},
                            "action_id": "open_create_channel",
                        },
                    ],
                }
            )

        blocks.append({"type": "divider"})
        blocks.append({"type": "header", "text": {"type": "plain_text", "text": "Settings & Danger Zone"}})
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Settings*"}})
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Edit Details"},
                        "action_id": "open_edit_project_modal",
                    }
                ],
            }
        )
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*⚠️ Danger Zone*"}})
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Archive Project"},
                        "action_id": "archive_project",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Leave Project"},
                        "action_id": "leave_project",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Delete Project"},
                        "action_id": "delete_project_confirm",
                        "style": "danger",
                        "confirm": {
                            "title": {"type": "plain_text", "text": "Delete this project?"},
                            "text": {
                                "type": "mrkdwn",
                                "text": "This action cannot be undone.",
                            },
                            "confirm": {"type": "plain_text", "text": "Delete"},
                            "deny": {"type": "plain_text", "text": "Cancel"},
                        },
                    },
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

    @staticmethod
    def render_project_hub(
        projects: list[dict[str, Any]],
        user_id: str,
        admin_user_id: str | None = None,
    ) -> dict:
        blocks: list[dict[str, Any]] = []
        blocks.extend(UIManager._nesta_header("🏛️ Discovery Hub", "Manage your missions and evidence."))
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "➕ Start New Mission"},
                        "action_id": "open_create_project_modal",
                        "style": "primary",
                    }
                ],
            }
        )
        if not projects:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "You don't have any projects yet."},
                }
            )
            if admin_user_id and user_id == admin_user_id:
                blocks.append({"type": "divider"})
                blocks.append(
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "🔐 Admin Dashboard"},
                                "action_id": "open_admin_dashboard",
                            }
                        ],
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
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "🔐 Admin Dashboard"},
                            "action_id": "open_admin_dashboard",
                        }
                    ],
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
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "🗑️ Purge 0-Member Projects"},
                        "action_id": "admin_purge_confirm",
                        "style": "danger",
                    }
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
                    "accessory": {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Delete"},
                        "action_id": "admin_delete_project",
                        "value": str(project.get("id")),
                        "style": "danger",
                    },
                }
            )
            blocks.append({"type": "divider"})
        return {"type": "home", "blocks": blocks}
