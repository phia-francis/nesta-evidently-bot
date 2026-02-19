import io
import json
import logging
import os
import re
import threading
import time
from functools import wraps
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib import error as url_error
from urllib import request as url_request
from aiohttp import web
from apscheduler.schedulers.background import BackgroundScheduler
import pandas as pd
import requests
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_bolt.workflows.step import WorkflowStep
from slack_sdk.errors import SlackApiError

from blocks.home_tab import get_home_view
from blocks.ui_manager import UIManager
from constants import (
    ASSUMPTION_DEFAULT_CATEGORY,
    HELP_ANALYSIS,
    HELP_HEADER,
    HELP_INTERVIEW,
    HELP_SETUP,
    HELP_TOOLKIT,
    HELP_WELCOME,
    PUBLIC_HOLIDAYS,
    WELCOME_GREETING,
    WELCOME_USAGE,
)
from blocks.interactions import (
    case_study_modal,
    decision_heatmap_label,
    decision_vote_modal,
    error_block,
    get_ai_summary_block,
    get_loading_block,
)
from blocks.modal_factory import ModalFactory
from blocks.nesta_ui import NestaUI
from blocks.onboarding import get_setup_step_1_modal, get_setup_step_2_modal
from blocks.modals import (
    add_canvas_item_modal,
    build_diagnostic_block_id,
    change_stage_modal,
    create_channel_modal,
    experiment_modal,
    get_edit_diagnostic_answer_modal,
    extract_insights_modal,
    get_diagnostic_modal,
    get_loading_modal,
    get_new_project_modal,
    get_roadmap_modal,
    invite_member_modal,
    link_channel_modal,
    open_log_assumption_modal,
    silent_scoring_modal,
)
from blocks.methods_ui import method_cards
from config import Config
from config_manager import ConfigManager
from services import knowledge_base
from services.ai_service import AiService, EvidenceAI
from services.db_service import DbService, engine
from services.decision_service import DecisionRoomService
from services.backup_service import BackupService
from services.google_workspace_service import GoogleWorkspaceService
from services.google_service import GoogleService
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from services.integration_service import IntegrationService
from services.ingestion_service import IngestionService
from services.messenger_service import MessengerService
from services.playbook_service import PlaybookService
from services.report_service import ReportService
from services.sync_service import TwoWaySyncService
from services.scheduler_service import start_scheduler
from services.toolkit_service import ToolkitService
from utils.diagnostic_utils import normalize_question_text


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAX_ASANA_PAYLOAD_ITEM_LENGTH = 100
CHANNEL_PREFIX = "evidently-"
ADMIN_USER_ID = os.environ.get("ADMIN_USER")
UNCERTAINTY_HORIZON_NOW_THRESHOLD = 4
UNCERTAINTY_HORIZON_LATER_THRESHOLD = 2

ConfigManager().validate()

app = App(token=Config.SLACK_BOT_TOKEN, signing_secret=Config.SLACK_SIGNING_SECRET)
ai_service = EvidenceAI()
ai_extractor = AiService()
db_service = DbService()
decision_service = DecisionRoomService(db_service)
playbook = PlaybookService()
integration_service = IntegrationService()
toolkit_service = ToolkitService()
ingestion_service = IngestionService(db_service=db_service)
sync_service = TwoWaySyncService()
messenger_service = MessengerService(app.client)
backup_service = BackupService()
google_service = GoogleService()
report_service = ReportService(ai_service, db_service)
try:
    google_workspace_service = GoogleWorkspaceService()
except Exception:  # noqa: BLE001
    logging.warning("Google Workspace credentials missing; exports disabled.")
    google_workspace_service = None


# --- WORKFLOW STEP: LOG EVIDENCE ---

# --- 1. Define the Workflow Functions First ---
def edit_log_evidence(ack, step, configure):  # noqa: ANN001
    ack()
    configure(
        blocks=[
            {
                "type": "input",
                "block_id": "project_block",
                "label": {"type": "plain_text", "text": "Project Name"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "project_name",
                    "placeholder": {"type": "plain_text", "text": "e.g. Healthy Start"},
                },
            },
            {
                "type": "input",
                "block_id": "evidence_block",
                "label": {"type": "plain_text", "text": "Evidence Data"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "evidence_text",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Insert variable here (e.g. form response)",
                    },
                },
            },
        ],
    )


def save_log_evidence(ack, view, update):  # noqa: ANN001
    ack()
    values = view["state"]["values"]
    project_name = values["project_block"]["project_name"]["value"]
    evidence_text = values["evidence_block"]["evidence_text"]["value"]

    update(
        inputs={
            "project_name": {"value": project_name},
            "evidence_text": {"value": evidence_text},
        },
    )


def execute_log_evidence(step, complete, fail):  # noqa: ANN001
    inputs = step["inputs"]
    project_name = inputs.get("project_name", {}).get("value")
    evidence_text = inputs.get("evidence_text", {}).get("value")

    try:
        project_id = db_service.find_project_by_fuzzy_name(project_name)
        if not project_id:
            fail(error={"message": f"Project not found for name: {project_name}"})
            return
        db_service.add_canvas_item(project_id, section="Progress", text=evidence_text or "")
        complete(outputs={"status": "success"})

    except Exception as exc:  # noqa: BLE001
        fail(error={"message": str(exc)})


# --- 2. Register the Step with All Listeners ---
# This prevents the "listener is required" error
ws = WorkflowStep(
    callback_id="log_evidence",
    edit=edit_log_evidence,
    save=save_log_evidence,
    execute=execute_log_evidence,
)

app.step(ws)

CHANNEL_TAB_TEMPLATES = {
    "experiments": {"title": "Experiments", "emoji": "🧪"},
    "manual": {"title": "Manual", "emoji": "📘"},
    "decisions": {"title": "Decisions", "emoji": "🗳️"},
}


def get_help_manual_blocks():
    return [
        {"type": "header", "text": {"type": "plain_text", "text": HELP_HEADER}},
        {"type": "section", "text": {"type": "mrkdwn", "text": HELP_WELCOME}},
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": HELP_SETUP,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": HELP_TOOLKIT,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": HELP_INTERVIEW.format(default_method=ToolkitService.DEFAULT_METHOD_NAME),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": HELP_ANALYSIS,
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Open Dashboard"},
                    "action_id": "refresh_home",
                    "style": "primary",
                }
            ],
        },
    ]


def get_project_status_blocks(project, metrics, user_id):
    score = int(project.get("innovation_score", 0))
    filled = min(5, max(0, round(score / 20)))
    progress_bar = "🟩" * filled + "⬜" * (5 - filled)
    return [
        {"type": "header", "text": {"type": "plain_text", "text": f"🚀 Project Status: {project['name']}"}},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Current Stage:*\n{project['stage']}"},
                {"type": "mrkdwn", "text": f"*Innovation Score:*\n{progress_bar} {score}%"},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"🧪 *Experiments Run:*\n{metrics.get('experiments', 0)}"},
                {"type": "mrkdwn", "text": f"✅ *Validated:*\n{metrics.get('validated', 0)}"},
                {"type": "mrkdwn", "text": f"🗑️ *Rejected:*\n{metrics.get('rejected', 0)}"},
            ],
        },
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"Status report generated by <@{user_id}>"}]},
    ]


def get_ask_blocks(method_name, formatted_questions):
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"📋 *Script: {method_name} Questions*"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": formatted_questions}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": "Copy these into your notes or read them aloud."}]},
    ]


def run_in_background(target, *args, **kwargs) -> None:
    thread = threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True)
    thread.start()


def download_private_file(url: str) -> bytes | None:
    request = url_request.Request(url, headers={"Authorization": f"Bearer {Config.SLACK_BOT_TOKEN}"})
    try:
        with url_request.urlopen(request, timeout=20) as response:  # noqa: S310
            return response.read()
    except url_error.URLError:
        logger.exception("Failed to download file")
        return None


async def handle_asana_webhook(request: web.Request) -> web.Response:
    """Handle Asana webhook events and sync experiment status."""
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)

    events = payload.get("events", [])
    for event in events:
        task = event.get("resource", {})
        task_id = task.get("gid")
        if not task_id:
            continue
        if event.get("action") not in {"changed", "added"}:
            continue
        if event.get("resource_type") != "task":
            continue
        change = event.get("change", {})
        if change.get("field") not in {"completed", "is_completed"}:
            continue
        completed_value = change.get("value")
        if completed_value is None:
            completed_value = change.get("new_value")
        if completed_value is not True:
            continue

        experiment = db_service.get_experiment_by_asana_task_id(task_id)
        if not experiment:
            continue
        decision = sync_service.resolve_status_conflict(experiment.get("status", ""), True)
        project = db_service.get_project(experiment["project_id"])
        if decision["action"] == "update_experiment":
            db_service.update_experiment(experiment["id"], status="Completed")
            if project and project.get("channel_id"):
                messenger_service.post_message(
                    channel=project["channel_id"],
                    text="✅ Task completed in Asana -> Experiment marked as Done in Slack.",
                )
        elif decision["action"] == "conflict" and project and project.get("channel_id"):
            messenger_service.post_message(
                channel=project["channel_id"],
                text=f"⚠️ Sync conflict: {decision['message']}",
            )

    return web.json_response({"ok": True})


def run_thread_analysis(client, channel_id: str, thread_ts: str, logger):  # noqa: ANN001
    loading_msg = client.chat_postMessage(
        channel=channel_id,
        blocks=get_loading_block("Analysing thread context..."),
        thread_ts=thread_ts,
        text="Analysing thread context...",
    )
    stop_animation = threading.Event()

    def animate_loading() -> None:
        statuses = [
            "Reading thread history... 📖",
            "Extracting hypotheses... 🧠",
            "Drafting summary... 📝",
        ]
        index = 0
        while not stop_animation.is_set():
            time.sleep(1.5)
            index = (index + 1) % len(statuses)
            try:
                client.chat_update(
                    channel=channel_id,
                    ts=loading_msg["ts"],
                    blocks=get_loading_block(statuses[index]),
                )
            except Exception:  # noqa: BLE001
                logger.debug("Unable to update loading animation", exc_info=True)

    def run_analysis() -> None:
        try:
            history = client.conversations_replies(channel=channel_id, ts=thread_ts)
            messages = history["messages"]
            full_text = "\n".join([f"{m.get('user')}: {m.get('text')}" for m in messages])

            attachments = [
                {"name": file.get("name"), "mimetype": file.get("mimetype")}
                for message in messages
                for file in message.get("files", []) or []
            ]

            analysis = ai_service.analyze_thread_structured(full_text, attachments)

            if analysis.get("error"):
                client.chat_update(
                    channel=channel_id,
                    ts=loading_msg["ts"],
                    blocks=error_block("The AI brain is briefly offline. Please try again."),
                    text="Analysis failed",
                )
                return

            project = db_service.get_project_by_channel(channel_id)
            if project:
                context_summary = ai_service.summarize_thread([m.get("text", "") for m in messages if m.get("text")])
                db_service.update_project_context(project["id"], context_summary)
                if project.get("flow_stage") == "audit":
                    ocp_answers = ai_service.analyze_for_ocp(full_text)
                    if not ocp_answers.get("error"):
                        analysis["ocp_answers"] = ocp_answers

            client.chat_update(
                channel=channel_id,
                ts=loading_msg["ts"],
                blocks=get_ai_summary_block(analysis),
                text="Analysis complete",
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Error handling mention: %s", exc, exc_info=True)
            client.chat_update(
                channel=channel_id,
                ts=loading_msg["ts"],
                text=f":warning: I crashed while thinking: {str(exc)}",
            )
        finally:
            stop_animation.set()

    animation_thread = threading.Thread(target=animate_loading, daemon=True)
    analysis_thread = threading.Thread(target=run_analysis, daemon=True)
    animation_thread.start()
    analysis_thread.start()


def parse_message_link(message_link: str) -> tuple[str | None, str | None]:
    match = re.search(r"/archives/(?P<channel>[A-Z0-9]+)/p(?P<ts>\d+)", message_link)
    if not match:
        return None, None
    channel_id = match.group("channel")
    ts_raw = match.group("ts")
    if len(ts_raw) <= 6:
        return None, None
    ts = f"{ts_raw[:-6]}.{ts_raw[-6:]}"
    return channel_id, ts


def extract_drive_file_id(link: str) -> str | None:
    patterns = [
        r"/d/([a-zA-Z0-9_-]+)",
        r"open\?id=([a-zA-Z0-9_-]+)",
        r"id=([a-zA-Z0-9_-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, link)
        if match:
            return match.group(1)
    return link.strip() or None


def save_assumptions_from_text(project_id: int, assumptions: list[str]) -> int:
    saved = 0
    for assumption_text in assumptions:
        if not assumption_text.strip():
            continue
        db_service.create_assumption(
            project_id,
            {
                "title": assumption_text.strip(),
                "lane": "Now",
                "validation_status": "Testing",
            },
        )
        saved += 1
    return saved


def apply_channel_template(client, channel_id: str, tabs: list[str]) -> None:
    if not tabs:
        return
    base_link = (
        f"https://slack.com/app_redirect?app={Config.SLACK_APP_ID}"
        if Config.SLACK_APP_ID
        else "https://slack.com/apps"
    )
    for tab in tabs:
        template = CHANNEL_TAB_TEMPLATES.get(tab)
        if not template:
            continue
        try:
            client.bookmarks_add(
                channel_id=channel_id,
                title=template["title"],
                emoji=template["emoji"],
                link=base_link,
            )
        except Exception:  # noqa: BLE001
            logger.warning("Unable to add channel tab template for %s.", tab, exc_info=True)


# --- 1. HOME TAB (OCP Dashboard) ---
def _set_active_project_from_channel(user_id: str, event: dict) -> None:
    channel_id = event.get("channel") or event.get("channel_id") or event.get("view", {}).get("channel_id")
    if not channel_id:
        return
    project = db_service.get_project_by_channel(channel_id)
    if project:
        db_service.set_active_project(user_id, project["id"])


@app.event("app_home_opened")
def update_home_tab(client, event, logger):  # noqa: ANN001
    try:
        user_id = event["user"]
        _set_active_project_from_channel(user_id, event)
        publish_home_tab_async(client, user_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("Error publishing home tab: %s", exc, exc_info=True)


def app_home_opened(client, event, logger):  # noqa: ANN001
    try:
        user_id = event["user"]
        _set_active_project_from_channel(user_id, event)
        publish_home_tab_async(client, user_id)
    except Exception as exc:  # noqa: BLE001
        if logger:
            logger.error("Error publishing home tab: %s", exc, exc_info=True)


@app.action("experiments_page_next")
@app.action("experiments_page_prev")
def handle_experiment_page_action(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    try:
        page = int(body["actions"][0]["value"])
    except (TypeError, ValueError):
        page = 0
    publish_home_tab_async(client, user_id, "overview", experiment_page=max(page, 0))


def publish_home_tab(
    client,
    user_id: str,
    active_tab: str = "overview",
    experiment_page: int = 0,
    plan_suggestion: str | None = None,
) -> None:
    project_data = db_service.get_active_project(user_id)
    all_projects = db_service.get_user_projects(user_id)
    view = get_home_view(
        user_id,
        project_data,
        all_projects,
        plan_suggestion=plan_suggestion,
        playbook_service=playbook,
    )
    client.views_publish(user_id=user_id, view=view)


def publish_home_tab_hub(client, user_id: str) -> None:
    projects = db_service.get_user_projects(user_id)
    view = UIManager.render_project_hub(projects, user_id, ADMIN_USER_ID)
    client.views_publish(user_id=user_id, view=view)


def _send_new_project_tour(client, user_id: str, project: dict) -> None:  # noqa: ANN001
    client.chat_postEphemeral(
        channel=user_id,
        user=user_id,
        text=f"👋 Welcome! I've set your project to Stage 1: {project.get('flow_stage', 'audit').title()}.",
    )
    client.chat_postEphemeral(
        channel=user_id,
        user=user_id,
        text="🎯 Goal: Answer the OCP questions to find your gaps.",
    )
    client.chat_postEphemeral(
        channel=user_id,
        user=user_id,
        text="👉 Click 'Run Diagnostic' to start.",
    )


def admin_required(func):  # noqa: ANN001
    @wraps(func)
    def decorated_function(ack, body, client, *args, **kwargs):  # noqa: ANN001
        user_id = body["user"]["id"]
        if not ADMIN_USER_ID or user_id != ADMIN_USER_ID:
            ack()
            client.chat_postEphemeral(channel=user_id, user=user_id, text="You are not authorized to perform this action.")
            return None
        return func(ack, body, client, *args, **kwargs)

    return decorated_function


def publish_home_tab_async(
    client,
    user_id: str,
    active_tab: str = "overview",
    experiment_page: int = 0,
    plan_suggestion: str | None = None,
) -> None:
    project_data = db_service.get_active_project(user_id)
    all_projects = db_service.get_user_projects(user_id)
    view = get_home_view(
        user_id,
        project_data,
        all_projects,
        plan_suggestion=plan_suggestion,
        playbook_service=playbook,
    )
    client.views_publish(user_id=user_id, view=view)

    if not project_data:
        return

    def update_actions() -> None:
        try:
            refreshed_view = get_home_view(
                user_id,
                project_data,
                all_projects,
                plan_suggestion=plan_suggestion,
                playbook_service=playbook,
            )
            client.views_publish(user_id=user_id, view=refreshed_view)
        except Exception:
            logger.exception("Failed to generate and publish next best actions for user %s", user_id)


@app.action("refresh_home")
def refresh_home(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    publish_home_tab_async(client, user_id)


@app.action("open_new_project_modal")
def open_new_project_modal(ack, body, client):  # noqa: ANN001
    ack()
    client.views_open(trigger_id=body["trigger_id"], view=get_new_project_modal())


@app.view("new_project_submit")
def handle_new_project_submit(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    values = body["view"]["state"]["values"]
    try:
        name = values["project_name"]["value"]["value"]
        description = values["project_description"]["value"]["value"]
        flow_stage = values["project_flow_stage"]["value"]["selected_option"]["value"]
        project = db_service.create_project(user_id=user_id, name=name, description=description, flow_stage=flow_stage)
        if project:
            publish_home_tab_async(client, user_id)
            _send_new_project_tour(client, user_id, project)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to create project via new modal", exc_info=True)
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Unable to create that project right now.")


@app.action("action_set_flow_stage")
def action_set_flow_stage(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    flow_stage = body["actions"][0].get("value")
    project = db_service.get_active_project(user_id)
    if not project or not flow_stage:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please select an active project first.")
        return
    db_service.update_project_flow_stage(project["id"], flow_stage)
    plan_suggestion = None
    if flow_stage == "plan":
        plan_suggestion = _get_plan_suggestion(project)
    publish_home_tab_async(client, user_id, "overview", plan_suggestion=plan_suggestion)


def _get_plan_suggestion(project: dict) -> str | None:
    assumptions = project.get("assumptions", [])
    unsorted = [
        assumption
        for assumption in assumptions
        if (assumption.get("horizon") or "").lower() not in {"now", "next", "later"}
        or (assumption.get("lane") or "").lower() == "unsorted"
    ]
    if not unsorted:
        return None
    target = unsorted[0]
    suggestion = ai_service.suggest_roadmap_horizon(target.get("title", ""))
    if suggestion.get("error"):
        return None
    horizon = suggestion.get("horizon", "now")
    reason = suggestion.get("reason", "critical risk to validate early")
    return f"💡 AI Suggestion: Move *{target.get('title', 'assumption')}* to *{horizon.upper()}* because {reason}."


def _build_diagnostic_question_map(
    framework: dict[str, dict[str, object]],
) -> dict[str, tuple[str, str, str]]:
    question_map: dict[str, tuple[str, str, str]] = {}
    for pillar_key, pillar_data in framework.items():
        sub_categories = pillar_data.get("sub_categories", {})
        for sub_category, sub_data in sub_categories.items():
            questions = sub_data if isinstance(sub_data, list) else sub_data.get("questions", [])
            for question in questions:
                base_id = build_diagnostic_block_id(pillar_key, sub_category, question)
                question_map[base_id] = (pillar_key, sub_category, question)
    return question_map


def _normalize_label(value: str | None) -> str:
    return (value or "").strip().lower()


def _match_framework_pillar(raw_category: str | None, framework: dict[str, dict[str, object]]) -> str:
    if not framework:
        return raw_category or ASSUMPTION_DEFAULT_CATEGORY
    default_pillar = next(iter(framework.keys()))
    if not raw_category:
        return default_pillar
    normalized = _normalize_label(raw_category)
    for pillar_key in framework.keys():
        normalized_pillar = _normalize_label(pillar_key)
        pillar_label = _normalize_label(pillar_key.split(". ", 1)[-1])
        if normalized in {normalized_pillar, pillar_label}:
            return pillar_key
    return default_pillar


def _find_diagnostic_assumption(
    assumptions: list[dict[str, Any]],
    pillar: str,
    sub_category: str,
    question: str,
) -> dict[str, Any] | None:
    target_key = (_normalize_label(pillar), _normalize_label(sub_category), normalize_question_text(question))
    for assumption in assumptions:
        assumption_key = (
            _normalize_label(assumption.get("category")),
            _normalize_label(assumption.get("sub_category")),
            normalize_question_text(assumption.get("title") or ""),
        )
        if assumption_key == target_key:
            return assumption
    return None


def _map_ai_response_to_diagnostic(
    framework: dict[str, dict[str, object]],
    ai_response: dict[str, Any],
) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, dict[str, str]]]]:
    pillar_lookup: dict[str, str] = {}
    for pillar_key in framework.keys():
        pillar_lookup[pillar_key.split(". ", 1)[-1].strip().lower()] = pillar_key
        pillar_lookup[pillar_key.strip().lower()] = pillar_key

    ai_data: dict[str, dict[str, object]] = {}
    roadmap_data: dict[str, dict[str, dict[str, str]]] = {}

    for pillar_name, pillar_payload in ai_response.items():
        if not isinstance(pillar_payload, dict):
            continue
        pillar_key = pillar_lookup.get(str(pillar_name).strip().lower())
        if not pillar_key:
            continue
        sub_categories = framework[pillar_key].get("sub_categories", {})
        sub_category_lookup = {
            sub_key.strip().lower(): sub_key for sub_key in sub_categories.keys()
        }
        for sub_name, sub_payload in pillar_payload.items():
            if not isinstance(sub_payload, dict):
                continue
            sub_category_key = sub_category_lookup.get(str(sub_name).strip().lower())
            if not sub_category_key:
                continue
            assumptions = sub_payload.get("assumptions", [])
            if isinstance(assumptions, list):
                for assumption in assumptions:
                    if not isinstance(assumption, dict):
                        continue
                    question_text = str(assumption.get("question", "")).strip()
                    if not question_text:
                        continue
                    base_id = build_diagnostic_block_id(pillar_key, sub_category_key, question_text)
                    ai_data[base_id] = {
                        "answer": str(assumption.get("answer", "")).strip(),
                        "confidence": assumption.get("confidence", ""),
                    }
            roadmap_payload = sub_payload.get("roadmap", {})
            if isinstance(roadmap_payload, dict):
                roadmap_data.setdefault(pillar_key, {})[sub_category_key] = {
                    "now": str(roadmap_payload.get("now", "")).strip(),
                    "next": str(roadmap_payload.get("next", "")).strip(),
                    "later": str(roadmap_payload.get("later", "")).strip(),
                }
    return ai_data, roadmap_data


@app.action("action_open_diagnostic")
def action_open_diagnostic(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        return
    framework = playbook.get_5_pillar_framework()
    client.views_open(
        trigger_id=body["trigger_id"],
        view=get_diagnostic_modal(framework, project_id=project["id"]),
    )


@app.action("autofill_diagnostic")
def autofill_diagnostic(ack, body, client, logger):  # noqa: ANN001
    ack()
    view = body.get("view", {})
    view_id = view.get("id")
    project_id = view.get("private_metadata") or body["actions"][0].get("value")
    if isinstance(project_id, str) and project_id.startswith("{"):
        try:
            metadata_payload = json.loads(project_id)
            if isinstance(metadata_payload, dict):
                project_id = metadata_payload.get("project_id")
        except json.JSONDecodeError:
            project_id = None
    if not view_id or not project_id:
        return
    try:
        context_text = ingestion_service.ingest_project_files(int(project_id))
        framework = playbook.get_5_pillar_framework()
        if not context_text:
            client.views_update(
                view_id=view_id,
                view=get_diagnostic_modal(
                    framework,
                    project_id=int(project_id),
                    status_message="⚠️ No connected evidence found. Add files to auto-fill.",
                ),
            )
            return
        ai_response = ai_service.extract_5_pillar_diagnostic(context_text)
        if not isinstance(ai_response, dict) or ai_response.get("error"):
            client.views_update(
                view_id=view_id,
                view=get_diagnostic_modal(
                    framework,
                    project_id=int(project_id),
                    status_message="⚠️ Unable to auto-fill from AI right now.",
                ),
            )
            return
        ai_data, roadmap_data = _map_ai_response_to_diagnostic(framework, ai_response)
        client.views_update(
            view_id=view_id,
            view=get_diagnostic_modal(
                framework,
                project_id=int(project_id),
                ai_data=ai_data,
                status_message="✨ Auto-filled from connected evidence.",
                private_metadata={"project_id": int(project_id), "ai_roadmap": roadmap_data},
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to auto-fill diagnostic", exc_info=True)


@app.view("action_save_diagnostic")
def action_save_diagnostic(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        return
    values = body["view"]["state"]["values"]
    try:
        framework = playbook.get_5_pillar_framework()
        question_map = _build_diagnostic_question_map(framework)
        answers: dict[str, str] = {}
        confidences: dict[str, int] = {}
        for block_id, block_values in values.items():
            if block_id.startswith("diagnostic_answer__"):
                lookup_key = block_id.replace("diagnostic_answer__", "")
                answers[lookup_key] = block_values.get("answer", {}).get("value", "").strip()
            if block_id.startswith("diagnostic_confidence__"):
                lookup_key = block_id.replace("diagnostic_confidence__", "")
                selection = block_values.get("confidence_score", {}).get("selected_option")
                if selection:
                    confidences[lookup_key] = int(selection["value"])
        for lookup_key, (pillar, sub_category, question) in question_map.items():
            score = confidences.get(lookup_key)
            if score is None:
                continue
            answer = answers.get(lookup_key)
            # 5-Pillar diagnostic answers are stored as generic assumptions to avoid overloading legacy categories.
            db_service.upsert_diagnostic_assumption(
                project["id"],
                pillar,
                sub_category,
                question,
                score,
                answer=answer,
            )
        metadata = body["view"].get("private_metadata") or ""
        try:
            metadata_payload = json.loads(metadata)
        except json.JSONDecodeError:
            metadata_payload = {}
        if not isinstance(metadata_payload, dict):
            metadata_payload = {}
        roadmap_payload = metadata_payload.get("ai_roadmap", {})
        if isinstance(roadmap_payload, dict):
            for pillar, subcategories in roadmap_payload.items():
                if not isinstance(subcategories, dict):
                    continue
                for sub_category, plans in subcategories.items():
                    if not isinstance(plans, dict):
                        continue
                    db_service.upsert_roadmap_plan(
                        project["id"],
                        pillar,
                        sub_category,
                        plans.get("now"),
                        plans.get("next"),
                        plans.get("later"),
                    )
        publish_home_tab_async(client, user_id, "overview")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to save audit scores: %s", exc, exc_info=True)


@app.action("open_edit_diagnostic_answer")
def open_edit_diagnostic_answer(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        return
    raw_value = body["actions"][0].get("value", "")
    try:
        payload = json.loads(raw_value) if raw_value else {}
    except json.JSONDecodeError:
        payload = {}
    pillar = payload.get("pillar")
    sub_category = payload.get("sub_category")
    question = payload.get("question") or raw_value
    if not pillar or not sub_category or not question:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Unable to open that diagnostic question.")
        return
    existing = _find_diagnostic_assumption(project.get("assumptions", []), pillar, sub_category, question)
    answer = existing.get("source_snippet") if existing else None
    confidence_score = existing.get("confidence_score") if existing else None
    client.views_open(
        trigger_id=body["trigger_id"],
        view=get_edit_diagnostic_answer_modal(
            pillar=pillar,
            sub_category=sub_category,
            question=question,
            answer=answer,
            confidence_score=confidence_score,
            project_id=project["id"],
        ),
    )


@app.view("save_diagnostic_answer")
def save_diagnostic_answer(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        return
    metadata = body["view"].get("private_metadata") or "{}"
    try:
        payload = json.loads(metadata)
    except json.JSONDecodeError:
        payload = {}
    pillar = payload.get("pillar")
    sub_category = payload.get("sub_category")
    question = payload.get("question")
    if not pillar or not sub_category or not question:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Missing diagnostic details.")
        return
    values = body["view"]["state"]["values"]
    answer = values.get("diagnostic_answer", {}).get("answer_input", {}).get("value", "").strip()
    selection = values.get("diagnostic_confidence", {}).get("confidence_score", {}).get("selected_option")
    try:
        confidence_score = int(selection["value"]) if selection else 0
    except (TypeError, ValueError):
        confidence_score = 0
    try:
        db_service.upsert_diagnostic_assumption(
            project["id"],
            pillar,
            sub_category,
            question,
            confidence_score,
            answer=answer or None,
        )
        publish_home_tab_async(client, user_id, "overview")
    except SQLAlchemyError as exc:
        logger.error("Failed to save diagnostic answer: %s", exc, exc_info=True)


@app.action("open_roadmap_modal")
def open_roadmap_modal(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        return
    raw_value = body["actions"][0].get("value", "")
    if "||" not in raw_value:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Select a roadmap section to edit.")
        return
    pillar, sub_category = raw_value.split("||", 1)
    existing_plan = db_service.get_roadmap_plan(project["id"], pillar, sub_category)
    client.views_open(
        trigger_id=body["trigger_id"],
        view=get_roadmap_modal(
            pillar=pillar,
            sub_category=sub_category,
            roadmap_plan=existing_plan,
            project_id=project["id"],
        ),
    )


@app.action("open_decision_vote")
def open_decision_vote(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    assumption_id = int(body["actions"][0]["value"])
    assumption = db_service.get_assumption(assumption_id)
    if not assumption:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Assumption not found.")
        return
    project = db_service.get_active_project(user_id)
    channel_id = project.get("channel_id") if project else user_id
    client.views_open(
        trigger_id=body["trigger_id"],
        view=decision_vote_modal(
            assumption_title=assumption.get("title", "Untitled"),
            assumption_id=assumption_id,
            channel_id=channel_id,
        ),
    )


@app.view("save_roadmap_plan")
def save_roadmap_plan(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    values = body["view"]["state"]["values"]
    try:
        metadata = json.loads(body["view"].get("private_metadata") or "{}")
        pillar = metadata.get("pillar")
        sub_category = metadata.get("sub_category")
        project_id = metadata.get("project_id")
        if not (pillar and sub_category and project_id):
            client.chat_postEphemeral(channel=user_id, user=user_id, text="Missing roadmap context.")
            return
        plan_now = values["roadmap_plan_now"]["plan_now"].get("value", "").strip()
        plan_next = values["roadmap_plan_next"]["plan_next"].get("value", "").strip()
        plan_later = values["roadmap_plan_later"]["plan_later"].get("value", "").strip()
        db_service.upsert_roadmap_plan(
            int(project_id),
            pillar,
            sub_category,
            plan_now,
            plan_next,
            plan_later,
        )
        publish_home_tab_async(client, user_id, "overview")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to update roadmap plan: %s", exc, exc_info=True)


@app.action("view_playbook_methods")
def view_playbook_methods(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    stage = project.get("stage", "Define") if project else "Define"
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "title": {"type": "plain_text", "text": "Playbook Methods"},
            "close": {"type": "plain_text", "text": "Close"},
            "blocks": method_cards(stage),
        },
    )


@app.action("generate_meeting_agenda")
def generate_meeting_agenda(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please select a project first.")
        return
    agenda = report_service.generate_meeting_agenda(project["id"])
    channel_id = project.get("channel_id") or user_id
    client.chat_postMessage(
        channel=channel_id,
        text="Meeting agenda",
        blocks=[
            {"type": "header", "text": {"type": "plain_text", "text": "📅 Meeting Agenda"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": agenda}},
        ],
    )


@app.action("export_strategy_doc")
def export_strategy_doc(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please select a project first.")
        return
    report_path = None
    try:
        report_path = report_service.generate_strategy_doc(project)
        channel_id = project.get("channel_id") or user_id
        client.files_upload_v2(
            channel=channel_id,
            title=f"Strategy Report · {project.get('name', 'Project')}",
            filename=f"strategy-report-{project.get('id', 'project')}.md",
            file=str(report_path),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to export strategy doc", exc_info=True)
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Unable to export the strategy doc right now.")
    finally:
        if report_path and report_path.exists():
            report_path.unlink()


@app.action(re.compile(r"^(nav|tab)_"))
def handle_navigation(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    tab = body["actions"][0]["value"]
    publish_home_tab_async(client, user_id, tab)


@app.action("open_project_dashboard")
def open_project_dashboard(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project_id = int(body["actions"][0]["value"])
    projects = db_service.get_user_projects(user_id)
    if not any(project["id"] == project_id for project in projects):
        client.chat_postEphemeral(channel=user_id, user=user_id, text="You don't have access to that project.")
        return
    db_service.set_active_project(user_id, project_id)
    publish_home_tab_async(client, user_id, "overview")


@app.action("draft_assumption_from_last_convo")
def draft_assumption_from_last_convo(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    try:
        project = db_service.get_active_project(user_id)
        channel_id = project.get("channel_id") if project else None
        if not channel_id:
            client.chat_postEphemeral(
                channel=user_id,
                user=user_id,
                text="Link a project channel first so I can read the latest conversation.",
            )
            return
        history = client.conversations_history(channel=channel_id, limit=10)
        messages = history.get("messages", [])
        if not messages:
            client.chat_postEphemeral(
                channel=user_id,
                user=user_id,
                text="No recent messages found to draft from.",
            )
            return
        conversation_text = "\n".join(message.get("text", "") for message in reversed(messages) if message.get("text"))
        analysis = ai_service.analyze_thread_structured(conversation_text)
        if analysis.get("error"):
            client.chat_postEphemeral(
                channel=user_id,
                user=user_id,
                text="I couldn't draft an assumption from that conversation yet.",
            )
            return
        assumption = (analysis.get("assumptions") or [{}])[0]
        ai_data = {
            "text": assumption.get("text", ""),
            "category": assumption.get("category", "Opportunity"),
        }
        client.views_open(
            trigger_id=body["trigger_id"],
            view=open_log_assumption_modal(ai_data),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to draft assumption from conversation", exc_info=True)
        client.chat_postEphemeral(
            channel=user_id,
            user=user_id,
            text="Something went wrong drafting the assumption.",
        )


@app.action("remove_drive_file")
def remove_drive_file(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    try:
        file_id = body["actions"][0].get("value")
        project = db_service.get_active_project(user_id)
        if not project or not file_id:
            client.chat_postEphemeral(channel=user_id, user=user_id, text="File not found.")
            return
        integrations = project.get("integrations") or {}
        drive_info = integrations.get("drive") or {}
        files = drive_info.get("files") or []
        updated_files = [item for item in files if item.get("id") != file_id]
        drive_info["files"] = updated_files
        integrations["drive"] = drive_info
        db_service.update_project_integrations(project["id"], integrations)
        publish_home_tab_async(client, user_id, "overview")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to remove drive file", exc_info=True)
        client.chat_postEphemeral(
            channel=user_id,
            user=user_id,
            text="Unable to remove that file right now.",
        )


@app.action("auto_fill_from_evidence")
def auto_fill_from_evidence(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    try:
        project = db_service.get_active_project(user_id)
        if not project:
            client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
            return
        context_text = ingestion_service.ingest_project_files(project["id"])
        if not context_text:
            client.chat_postEphemeral(
                channel=user_id,
                user=user_id,
                text="No readable evidence found in the connected files.",
            )
            return
        draft = ai_service.extract_ocp_from_text(context_text)
        if draft.get("error"):
            client.chat_postEphemeral(
                channel=user_id,
                user=user_id,
                text="I couldn't generate an OCP draft from that evidence yet.",
            )
            return
        description = (
            "Opportunity:\n"
            f"User Needs: {draft.get('Opportunity', {}).get('User Needs', '')}\n"
            f"Market Size: {draft.get('Opportunity', {}).get('Market Size', '')}\n\n"
            "Capability:\n"
            f"Resources: {draft.get('Capability', {}).get('Resources', '')}\n"
            f"Partners: {draft.get('Capability', {}).get('Partners', '')}\n\n"
            "Progress:\n"
            f"Solution Description: {draft.get('Progress', {}).get('Solution Description', '')}\n"
            f"Unique Selling Point: {draft.get('Progress', {}).get('Unique Selling Point', '')}"
        ).strip()
        db_service.update_project_details(
            project_id=project["id"],
            name=project.get("name", ""),
            description=description,
            mission=project.get("mission", ""),
        )
        insights = draft.get("Insights") or []
        insights_text = "\n- ".join(insights)
        if insights_text:
            messenger_service.post_ephemeral(
                channel=user_id,
                user=user_id,
                text=f"✅ Auto-fill complete. Insights:\n- {insights_text}",
            )
        publish_home_tab_async(client, user_id, "overview")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to auto-fill from evidence", exc_info=True)
        client.chat_postEphemeral(
            channel=user_id,
            user=user_id,
            text="Something went wrong while auto-filling from evidence.",
        )


@app.action("back_to_hub")
def back_to_hub(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    publish_home_tab_hub(client, user_id)


@app.action("open_admin_dashboard")
@admin_required
def open_admin_dashboard(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    all_projects = db_service.get_all_projects_with_counts()
    view = UIManager.render_admin_dashboard(all_projects)
    client.views_publish(user_id=user_id, view=view)


@app.action("admin_purge_confirm")
@admin_required
def admin_purge_confirm(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    all_projects = db_service.get_all_projects_with_counts()
    empty_count = sum(1 for project in all_projects if project.get("member_count", 0) == 0)
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "admin_purge_submit",
            "title": {"type": "plain_text", "text": "Confirm Purge"},
            "submit": {"type": "plain_text", "text": "Purge"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "private_metadata": json.dumps({"empty_count": empty_count}),
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Are you sure you want to delete *{empty_count}* empty projects?",
                    },
                }
            ],
        },
    )


@app.view("admin_purge_submit")
@admin_required
def admin_purge_submit(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    deleted_count = db_service.delete_empty_projects()
    client.chat_postEphemeral(
        channel=user_id,
        user=user_id,
        text=f"✅ Deleted {deleted_count} empty project(s).",
    )
    all_projects = db_service.get_all_projects_with_counts()
    view = UIManager.render_admin_dashboard(all_projects)
    client.views_publish(user_id=user_id, view=view)


@app.action("admin_delete_project")
@admin_required
def admin_delete_project(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project_id = int(body["actions"][0]["value"])
    db_service.delete_project(project_id)
    client.chat_postEphemeral(channel=user_id, user=user_id, text="Project deleted.")
    all_projects = db_service.get_all_projects_with_counts()
    view = UIManager.render_admin_dashboard(all_projects)
    client.views_publish(user_id=user_id, view=view)


@app.action("setup_step_1")
def start_setup(ack, body, client):  # noqa: ANN001
    ack()
    client.views_open(trigger_id=body["trigger_id"], view=get_setup_step_1_modal())


@app.action("open_create_project_modal")
def open_create_modal(ack, body, client):  # noqa: ANN001
    ack()
    client.views_open(
        trigger_id=body["trigger_id"],
        view=UIManager.render_create_project_modal(),
    )


@app.view("create_project_submit")
def handle_create_project(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    values = body["view"]["state"]["values"]

    # 1. Extract Values
    name = values["name_block"]["name"]["value"]
    opportunity = values["opportunity_block"]["opportunity_input"]["value"]
    capability = values["capability_block"]["capability_input"]["value"]
    progress = values["progress_block"]["progress_input"]["value"]

    # Extract Mission (Safety check ensures it doesn't crash if block is missing)
    mission = None
    if "mission_block" in values:
        mission = values["mission_block"]["mission_select"]["selected_option"]["value"]

    # Extract Channel Choice
    channel_action = "create_new"
    if "channel_block" in values:
        channel_action = values["channel_block"]["channel_action"]["selected_option"]["value"]

    # 2. Channel Creation Logic
    channel_id = None
    if channel_action == "create_new":
        # Create channel logic... (keep your existing logic here)
        clean_name = f"evidently-{name.lower().replace(' ', '-')}"[:80]
        try:
            c_resp = client.conversations_create(name=clean_name)
            channel_id = c_resp["channel"]["id"]
            client.conversations_invite(channel=channel_id, users=user_id)
        except Exception as e:
            logger.error("Failed to create channel '%s': %s", clean_name, e, exc_info=True)
            client.chat_postEphemeral(
                channel=user_id,
                user=user_id,
                text=f"I couldn't create a channel for your project. It might be a permissions issue or an invalid name. The project was created without a linked channel."
            )

    # 3. Create in DB (Pass the 'mission' variable!)
    db_service.create_project(
        user_id,
        name,
        opportunity=opportunity,
        capability=capability,
        progress=progress,
        mission=mission,
        channel_id=channel_id,
    )
    project = db_service.get_active_project(user_id)
    if project:
        _send_new_project_tour(client, user_id, project)

    # 4. Refresh Home
    app_home_opened(client, {"user": user_id}, None)


@app.action("create_collection_modal")
def open_collection_modal(ack, body, client):  # noqa: ANN001
    ack()
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "create_collection_submit",
            "title": {"type": "plain_text", "text": "New Collection"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "name",
                    "label": {"type": "plain_text", "text": "Name"},
                    "element": {"type": "plain_text_input", "action_id": "val"},
                },
                {
                    "type": "input",
                    "block_id": "desc",
                    "label": {"type": "plain_text", "text": "Description"},
                    "element": {"type": "plain_text_input", "action_id": "val", "multiline": True},
                },
            ],
            "submit": {"type": "plain_text", "text": "Create"},
        },
    )


@app.view("create_collection_submit")
def create_collection_submit(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    try:
        data = body["view"]["state"]["values"]
        name = data["name"]["val"]["value"]
        description = data["desc"]["val"]["value"]
        project = db_service.get_active_project(user_id)
        if not project:
            client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
            return
        db_service.create_collection(project["id"], name, description)
        publish_home_tab_async(client, user_id, "roadmap:collections")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to create collection: %s", exc, exc_info=True)


@app.action("create_automation_modal")
def open_automation_modal(ack, body, client):  # noqa: ANN001
    ack()
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "create_rule_submit",
            "title": {"type": "plain_text", "text": "New Automation Rule"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "trigger",
                    "label": {"type": "plain_text", "text": "When this happens..."},
                    "element": {
                        "type": "static_select",
                        "action_id": "val",
                        "options": [
                            {
                                "text": {"type": "plain_text", "text": "Experiment Created"},
                                "value": "experiment_created",
                            },
                            {
                                "text": {"type": "plain_text", "text": "Assumption Validated"},
                                "value": "assumption_validated",
                            },
                            {"text": {"type": "plain_text", "text": "Every Monday"}, "value": "weekly_schedule"},
                        ],
                    },
                },
                {
                    "type": "input",
                    "block_id": "action",
                    "label": {"type": "plain_text", "text": "Do this..."},
                    "element": {
                        "type": "static_select",
                        "action_id": "val",
                        "options": [
                            {
                                "text": {"type": "plain_text", "text": "Notify Project Channel"},
                                "value": "notify_channel",
                            },
                            {"text": {"type": "plain_text", "text": "Email Team Lead"}, "value": "email_lead"},
                        ],
                    },
                },
            ],
            "submit": {"type": "plain_text", "text": "Save Rule"},
        },
    )


@app.view("create_rule_submit")
def create_rule_submit(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    try:
        data = body["view"]["state"]["values"]
        trigger = data["trigger"]["val"]["selected_option"]["value"]
        action = data["action"]["val"]["selected_option"]["value"]
        project = db_service.get_active_project(user_id)
        if not project:
            client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
            return
        db_service.create_automation_rule(project["id"], trigger, action)
        publish_home_tab_async(client, user_id, "team:automation")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to create automation rule: %s", exc, exc_info=True)


@app.action("select_active_project")
def handle_project_switch(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    selected_project_id = body["actions"][0]["selected_option"]["value"]
    db_service.set_active_project(user_id, int(selected_project_id))
    publish_home_tab_async(client, user_id)


@app.view("setup_step_2_submit")
def handle_step_1(ack, body, client):  # noqa: ANN001
    problem = body["view"]["state"]["values"]["problem_block"]["problem_input"]["value"]
    ack(response_action="push", view=get_setup_step_2_modal(problem))


@app.command("/evidently-help")
def handle_help_command(ack, body, client):  # noqa: ANN001
    """
    Opens the Instruction Manual / Help Guide.
    """
    ack()
    user_id = body["user_id"]
    blocks = UIManager.render_help_guide()
    client.chat_postEphemeral(
        channel=body["channel_id"],
        user=user_id,
        text="Evidently Help Guide",
        blocks=blocks,
    )


@app.command("/evidently-link")
def handle_link_project(ack, body, respond, client, logger):  # noqa: ANN001
    ack()
    try:
        project_name = (body.get("text") or "").strip()
        if not project_name:
            client.views_open(trigger_id=body["trigger_id"], view=link_channel_modal())
            return
        user_projects = db_service.get_user_projects(body["user_id"])
        normalized_name = project_name.lower()
        exact_matches = [
            item for item in user_projects if item.get("name", "").lower() == normalized_name
        ]
        matches = exact_matches or [
            item for item in user_projects if normalized_name in item.get("name", "").lower()
        ]
        if len(matches) != 1:
            client.views_open(trigger_id=body["trigger_id"], view=link_channel_modal())
            return
        project = matches[0]
        project_id = project["id"]
        db_service.set_project_channel(project_id, body["channel_id"])
        db_service.set_active_project(body["user_id"], project_id)
        respond(f"✅ Channel linked to *{project['name']}*.")
        publish_home_tab_async(client, body["user_id"])
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to link project via command", exc_info=True)
        respond("Unable to link project right now.")


@app.command("/evidently-log")
def handle_log_command(ack, body, client, logger):  # noqa: ANN001
    ack()
    channel_id = body["channel_id"]
    trigger_id = body["trigger_id"]
    try:
        loading_response = client.views_open(trigger_id=trigger_id, view=get_loading_modal())
        view_id = loading_response["view"]["id"]
    except SlackApiError as exc:
        logger.error("Failed to open loading modal for log command: %s", exc, exc_info=True)
        return

    def background_task() -> None:
        ai_data = None
        try:
            history = client.conversations_history(channel=channel_id, limit=10)
            messages = history.get("messages", [])
            if messages:
                conversation_text = "\n".join(
                    message.get("text", "")
                    for message in reversed(messages)
                    if message.get("text")
                )
                attachments = [
                    {"name": file.get("name"), "mimetype": file.get("mimetype")}
                    for message in messages
                    for file in message.get("files", []) or []
                ]
                analysis = ai_service.analyze_thread_structured(conversation_text, attachments)
                if analysis and not analysis.get("error"):
                    assumption = (analysis.get("assumptions") or [{}])[0]
                    ai_data = {
                        "text": assumption.get("text", ""),
                    }
            client.views_update(view_id=view_id, view=open_log_assumption_modal(ai_data))
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to run log command in background", exc_info=True)
            client.views_update(view_id=view_id, view=open_log_assumption_modal())
    run_in_background(background_task)


@app.command("/evidently-agenda")
def handle_agenda_command(ack, body, client, logger):  # noqa: ANN001
    ack()
    try:
        channel_id = body["channel_id"]
        project = db_service.get_project_by_channel(channel_id)
        if not project:
            project = db_service.get_active_project(body["user_id"])
        if not project:
            client.chat_postEphemeral(
                channel=channel_id,
                user=body["user_id"],
                text="Please link a project to this channel first.",
            )
            return
        agenda = report_service.generate_meeting_agenda(project["id"])
        client.chat_postMessage(
            channel=channel_id,
            text="Meeting agenda",
            blocks=[
                {"type": "header", "text": {"type": "plain_text", "text": "📅 Meeting Agenda"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": agenda}},
            ],
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to generate agenda", exc_info=True)
        client.chat_postEphemeral(
            channel=body["channel_id"],
            user=body["user_id"],
            text="Unable to generate the agenda right now.",
        )


@app.command("/evidently-feedback")
def handle_feedback_command(ack, body, client):  # noqa: ANN001
    ack()
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "feedback_submit",
            "title": {"type": "plain_text", "text": "Send Feedback"},
            "submit": {"type": "plain_text", "text": "Send"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "feedback_text",
                    "label": {"type": "plain_text", "text": "Your feedback"},
                    "element": {"type": "plain_text_input", "action_id": "feedback_input", "multiline": True},
                }
            ],
        },
    )


@app.view("feedback_submit")
def handle_feedback_submit(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    feedback_text = body["view"]["state"]["values"]["feedback_text"]["feedback_input"]["value"]
    if not ADMIN_USER_ID:
        client.chat_postMessage(
            channel=user_id,
            text="Thanks for the feedback! The admin channel isn't configured yet.",
        )
        return
    try:
        client.chat_postMessage(
            channel=ADMIN_USER_ID,
            text=f"📝 Feedback from <@{user_id}>:\n{feedback_text}",
        )
        client.chat_postMessage(
            channel=user_id,
            text="✅ Your feedback was sent. Thank you!",
        )
    except SlackApiError as exc:
        logger.error("Failed to send feedback: %s", exc, exc_info=True)
        client.chat_postMessage(
            channel=user_id,
            text="❌ Something went wrong sending your feedback. Please try again.",
        )


@app.command("/evidently-status")
def handle_status_command(ack, body, client):  # noqa: ANN001
    """
    Posts a public 'Project Health Card' to the channel.
    """
    ack()
    user_id = body["user_id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=body["channel_id"], user=user_id, text="Please create a project first.")
        return

    metrics = db_service.get_metrics(project["id"])
    blocks = get_project_status_blocks(project, metrics, user_id)

    client.chat_postMessage(
        channel=body["channel_id"],
        blocks=blocks,
        text=f"Project Status: {project['name']}",
    )


@app.command("/evidently-fix-db")
def handle_db_fix(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user_id"]
    if user_id not in getattr(Config, "ADMIN_USERS", []):
        client.chat_postEphemeral(
            channel=user_id,
            user=user_id,
            text="⛔ You are not authorized to run this command.",
        )
        return
    client.chat_postEphemeral(
        channel=user_id,
        user=user_id,
        text="🛠️ Attempting to patch database schema...",
    )
    statements = [
        "ALTER TABLE projects ADD COLUMN dashboard_message_ts VARCHAR",
        "ALTER TABLE projects ADD COLUMN dashboard_channel_id VARCHAR",
        "ALTER TABLE assumptions ADD COLUMN category VARCHAR",
        "ALTER TABLE assumptions ADD COLUMN evidence_link VARCHAR",
        "ALTER TABLE experiments ADD COLUMN outcome VARCHAR",
    ]
    with engine.begin() as connection:
        for statement in statements:
            try:
                connection.execute(text(statement))
            except SQLAlchemyError:
                logger.info("Skipping schema update for statement: %s", statement)

    client.chat_postEphemeral(
        channel=user_id,
        user=user_id,
        text="✅ Database schema patched successfully.",
    )


@app.command("/evidently-ask")
def handle_ask_command(ack, body, client):  # noqa: ANN001
    """
    Instantly fetches interview questions for a specific method.
    Usage: /evidently-ask [method]
    """
    ack()
    user_id = body["user_id"]
    text = body.get("text", "").strip()
    method_name = text if text else ToolkitService.DEFAULT_METHOD_NAME

    questions = toolkit_service.get_question_bank(method_name)
    formatted_questions = "\n".join([f"• {question}" for question in questions])
    blocks = get_ask_blocks(method_name, formatted_questions)
    client.chat_postEphemeral(
        channel=body["channel_id"],
        user=user_id,
        blocks=blocks,
        text=f"{method_name} questions",
    )


@app.command("/evidently-scout")
def handle_scout_command(ack, body, client):  # noqa: ANN001
    """AI Research Assistant that finds competitors and market risks."""
    ack()
    user_id = body["user_id"]
    channel_id = body["channel_id"]
    region = body.get("text", "").strip() or "Global"
    project = db_service.get_active_project(user_id)

    if not project:
        client.chat_postEphemeral(channel=channel_id, user=user_id, text="No active project found.")
        return

    problem_statement = (project.get("description") or "").strip()
    if not problem_statement:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="Add a project description before running Market Scout.",
        )
        return

    client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text="🕵️ Scouting the market... analyzing competitors and risks...",
    )

    analysis = ai_service.scout_market(problem_statement, region=region)
    competitors = analysis.get("competitors", [])
    risks = analysis.get("risks", [])
    competitors_text = "\n".join([f"• {item}" for item in competitors]) or "No competitors returned."
    risks_text = "\n".join([f"• {item}" for item in risks]) or "No risks returned."

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"🕵️ Market Scout: {project['name']}"}},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Based on your problem statement, here is the landscape:*",
            },
        },
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"⚔️ *Potential Competitors:*\n{competitors_text}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"⚠️ *Market Risks:*\n{risks_text}"}},
    ]

    if analysis.get("raw") and not competitors and not risks:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Raw output:*\n{analysis['raw']}"},
            }
        )

    client.chat_postMessage(channel=channel_id, blocks=blocks, text="Market scout results")


@app.event("file_shared")
def handle_setup_files(event, client, logger):  # noqa: ANN001
    file_id = event.get("file_id")
    user_id = event.get("user_id")
    if not file_id or not user_id:
        return

    file_info = client.files_info(file=file_id).get("file", {})
    channels = file_info.get("channels", [])
    if not channels:
        return

    channel_id = channels[0]
    messenger_service.post_ephemeral(
        channel=channel_id,
        user=user_id,
        text=f"📄 I see you uploaded *{file_info.get('name', 'a file')}*. Want me to auto-fill your Canvas?",
        blocks=ModalFactory.file_analysis_prompt(file_info.get("name", "this file"), file_id),
    )


@app.action("ignore_file")
def ignore_file_upload(ack):  # noqa: ANN001
    ack()


@app.action("analyze_file")
def process_file_analysis(ack, body, client, logger):  # noqa: ANN001
    ack()
    file_id = body["actions"][0]["value"]
    channel_id = body["channel"]["id"]
    user_id = body["user"]["id"]

    messenger_service.post_ephemeral(
        channel=channel_id,
        user=user_id,
        text="🧠 Reading document... extracting assumptions...",
    )

    file_info = client.files_info(file=file_id).get("file", {})
    download_url = file_info.get("url_private_download")
    if not download_url:
        messenger_service.post_ephemeral(channel=channel_id, user=user_id, text="I couldn't access that file.")
        return

    file_content = download_private_file(download_url)
    if not file_content:
        messenger_service.post_ephemeral(channel=channel_id, user=user_id, text="I couldn't download that file.")
        return

    file_type = file_info.get("mimetype", "")
    extraction = ingestion_service.extract_text_payload(file_content, file_type)
    if extraction.get("error"):
        messenger_service.post_ephemeral(
            channel=channel_id,
            user=user_id,
            text=extraction["error"],
        )
        return

    chunks = extraction.get("chunks", [])
    context_text = "\n".join(chunks[:3]) if chunks else extraction.get("text", "")
    analysis = ai_service.generate_canvas_from_doc(context_text)
    project = db_service.get_active_project(user_id)
    if not project:
        messenger_service.post_ephemeral(channel=channel_id, user=user_id, text="No active project found.")
        return

    canvas_data = analysis.get("canvas_data", {})
    gaps = analysis.get("gaps_identified", [])
    follow_ups = analysis.get("follow_up_questions", [])
    summary_blocks = ModalFactory.document_insights_blocks(canvas_data, gaps, follow_ups)
    messenger_service.post_message(channel=channel_id, blocks=summary_blocks, text="Document insights")

    if canvas_data.get("problem"):
        db_service.add_canvas_item(project["id"], "Opportunity", canvas_data["problem"], is_ai=True)
    if canvas_data.get("solution"):
        db_service.add_canvas_item(project["id"], "Capability", canvas_data["solution"], is_ai=True)
    if canvas_data.get("users"):
        db_service.add_canvas_item(
            project["id"],
            "Opportunity",
            "Target users: " + ", ".join(canvas_data["users"]),
            is_ai=True,
        )

    for risk in canvas_data.get("risks", []):
        payload = json.dumps({"project_id": project["id"], "risk": risk})
        messenger_service.post_message(
            channel=channel_id,
            text="Review Assumption",
            blocks=ModalFactory.suggested_assumption_blocks(risk, payload),
        )


@app.action("accept_suggestion")
def accept_suggestion(ack, body, client):  # noqa: ANN001
    ack()
    payload = json.loads(body["actions"][0]["value"])
    similar_title = db_service.find_similar_assumption(payload["project_id"], payload["risk"])
    if similar_title:
        messenger_service.post_ephemeral(
            channel=body["channel"]["id"],
            user=body["user"]["id"],
            text=f"⚠️ This looks similar to: “{similar_title}”.",
        )
    db_service.create_assumption(payload["project_id"], {"title": payload["risk"]})
    messenger_service.post_ephemeral(
        channel=body["channel"]["id"],
        user=body["user"]["id"],
        text="✅ Added to your assumption board.",
    )


@app.action("reject_suggestion")
def reject_suggestion(ack, body, client):  # noqa: ANN001
    ack()
    client.chat_postEphemeral(
        channel=body["channel"]["id"],
        user=body["user"]["id"],
        text="Ignored that suggestion.",
    )


@app.action("edit_suggestion")
def edit_suggestion(ack, body, client):  # noqa: ANN001
    ack()
    payload = body["actions"][0]["value"]
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "edit_suggestion_submit",
            "private_metadata": payload,
            "title": {"type": "plain_text", "text": "Edit Assumption"},
            "submit": {"type": "plain_text", "text": "Save"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "risk_block",
                    "label": {"type": "plain_text", "text": "Assumption"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "risk_input",
                        "initial_value": json.loads(payload)["risk"],
                    },
                }
            ],
        },
    )


@app.view("edit_suggestion_submit")
def handle_edit_suggestion_submit(ack, body, client):  # noqa: ANN001
    ack()
    payload = json.loads(body["view"]["private_metadata"])
    values = body["view"]["state"]["values"]
    risk_text = values["risk_block"]["risk_input"]["value"]
    similar_title = db_service.find_similar_assumption(payload["project_id"], risk_text)
    response = client.conversations_open(users=body["user"]["id"])
    dm_channel = response.get("channel", {}).get("id")

    if similar_title and dm_channel:
        messenger_service.post_ephemeral(
            channel=dm_channel,
            user=body["user"]["id"],
            text=f"⚠️ This looks similar to: “{similar_title}”."
        )

    db_service.create_assumption(payload["project_id"], {"title": risk_text})

    if dm_channel:
        client.chat_postMessage(channel=dm_channel, text="✅ Added the edited assumption.")


@app.view("setup_final_submit")
def handle_final_setup(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    try:
        values = body["view"]["state"]["values"]
        problem = body["view"]["private_metadata"]
        name = values["name_block"]["name_input"]["value"]
        stage = values["stage_block"]["stage_input"]["selected_option"]["value"]
        mission = values["mission_block"]["mission_select"]["selected_option"]["value"]
        channel_action = values["channel_block"]["channel_action"]["selected_option"]["value"]

        channel_id = None
        created_channel_name = None

        if channel_action == "create_new":
            clean_name = re.sub(r"[^a-z0-9-_]", "", name.lower().replace(" ", "-"))
            channel_name = f"{CHANNEL_PREFIX}{clean_name}"[:80]
            try:
                c_resp = client.conversations_create(name=channel_name)
                channel_id = c_resp["channel"]["id"]
                created_channel_name = c_resp["channel"]["name"]
                client.conversations_invite(channel=channel_id, users=user_id)
                client.chat_postMessage(
                    channel=channel_id,
                    text=f"👋 Welcome to the home of *{name}*! I'll post updates here.",
                )
            except SlackApiError as exc:
                logger.error("Failed to create channel %s: %s", channel_name, exc, exc_info=True)
                client.chat_postEphemeral(
                    user=user_id,
                    channel=user_id,
                    text=f"⚠️ Could not create channel #{channel_name} (it might already exist).",
                )

        db_service.create_project(
            user_id,
            name,
            opportunity=problem,
            capability="",
            progress="",
            stage=stage,
            mission=mission,
            channel_id=channel_id,
        )
        project = db_service.get_active_project(user_id)
        if project:
            _send_new_project_tour(client, user_id, project)

        msg_text = f"🎉 *{name}* is live!"
        if created_channel_name:
            msg_text += f"\nI've created <#{channel_id}> for your team."

        blocks = [
            NestaUI.header(f"🎉 {name} is live!"),
            NestaUI.section(
                f"We've set your stage to *{stage}* and mission to *{mission}*.\n"
                "Add your first assumption to start de-risking."
            ),
        ]
        if created_channel_name:
            blocks.append(NestaUI.section(f"I've created <#{channel_id}> for your team."))
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "+ Add Assumption"},
                        "action_id": "open_create_assumption",
                    }
                ],
            }
        )

        client.chat_postMessage(
            channel=user_id,
            blocks=blocks,
            text=msg_text,
        )
        publish_home_tab_async(client, user_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to complete setup: %s", exc, exc_info=True)
        client.chat_postEphemeral(
            user=user_id,
            channel=user_id,
            text="Something went wrong creating the project.",
        )


def open_assumption_modal(client, trigger_id: str) -> None:
    client.views_open(
        trigger_id=trigger_id,
        view=UIManager.render_create_assumption_modal(),
    )


@app.action("assumption_category_select")
def handle_assumption_category_select(ack, body, client, logger):  # noqa: ANN001
    ack()
    try:
        selected_category = body["actions"][0]["selected_option"]["value"]
        view = body.get("view", {})
        values = view.get("state", {}).get("values", {})
        initial_values = {
            "title": values.get("assumption_title", {}).get("title_input", {}).get("value", ""),
            "lane": values.get("assumption_lane", {}).get("lane_input", {}).get("selected_option", {}).get("value"),
            "status": values.get("assumption_status", {}).get("status_input", {}).get("selected_option", {}).get("value"),
            "density": values.get("assumption_density", {}).get("density_input", {}).get("value", ""),
            "evidence_link": values.get("assumption_evidence_link", {})
            .get("evidence_link_input", {})
            .get("value", ""),
        }
        if view.get("private_metadata") == "ai_draft":
            ai_data = {
                "text": initial_values["title"],
                "category": selected_category,
                "lane": initial_values["lane"],
                "status": initial_values["status"],
            }
            client.views_update(
                view_id=view["id"],
                view=open_log_assumption_modal(ai_data),
            )
        else:
            client.views_update(
                view_id=view["id"],
                view=UIManager.render_create_assumption_modal(selected_category, initial_values),
            )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to update assumption modal prompts", exc_info=True)


def open_edit_assumption_modal(client, trigger_id: str, assumption: dict) -> None:
    lane_options = [
        {"text": {"type": "plain_text", "text": "Now"}, "value": "Now"},
        {"text": {"type": "plain_text", "text": "Next"}, "value": "Next"},
        {"text": {"type": "plain_text", "text": "Later"}, "value": "Later"},
    ]
    status_options = [
        {"text": {"type": "plain_text", "text": "Testing"}, "value": "Testing"},
        {"text": {"type": "plain_text", "text": "Validated"}, "value": "Validated"},
        {"text": {"type": "plain_text", "text": "Rejected"}, "value": "Rejected"},
    ]
    lane_option = next((option for option in lane_options if option["value"] == assumption["lane"]), None)
    status_option = next(
        (option for option in status_options if option["value"] == assumption["validation_status"]),
        None,
    )
    client.views_open(
        trigger_id=trigger_id,
        view={
            "type": "modal",
            "callback_id": "edit_assumption_submit",
            "private_metadata": str(assumption["id"]),
            "title": {"type": "plain_text", "text": "Edit Roadmap Item"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "assumption_title",
                    "label": {"type": "plain_text", "text": "Roadmap item"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "title_input",
                        "initial_value": assumption["title"],
                    },
                },
                {
                    "type": "input",
                    "block_id": "assumption_lane",
                    "label": {"type": "plain_text", "text": "Lane"},
                    "element": {
                        "type": "static_select",
                        "action_id": "lane_input",
                        "options": lane_options,
                        "initial_option": lane_option or lane_options[0],
                    },
                },
                {
                    "type": "input",
                    "block_id": "assumption_status",
                    "label": {"type": "plain_text", "text": "Validation status"},
                    "element": {
                        "type": "static_select",
                        "action_id": "status_input",
                        "options": status_options,
                        "initial_option": status_option or status_options[0],
                    },
                },
                {
                    "type": "input",
                    "block_id": "assumption_density",
                    "label": {"type": "plain_text", "text": "Evidence density (docs)"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "density_input",
                        "initial_value": str(assumption.get("evidence_density", 0)),
                    },
                },
            ],
            "submit": {"type": "plain_text", "text": "Save"},
        },
    )


def open_edit_assumption_text_modal(client, trigger_id: str, assumption: dict) -> None:
    client.views_open(
        trigger_id=trigger_id,
        view={
            "type": "modal",
            "callback_id": "edit_assumption_text_submit",
            "private_metadata": str(assumption["id"]),
            "title": {"type": "plain_text", "text": "Edit Assumption"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "submit": {"type": "plain_text", "text": "Save"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "assumption_text",
                    "label": {"type": "plain_text", "text": "Assumption text"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "text_input",
                        "initial_value": assumption.get("title", ""),
                        "multiline": True,
                    },
                }
            ],
        },
    )


@app.action("open_create_assumption")
@app.action("open_add_assumption")
def open_create_assumption_modal(ack, body, client):  # noqa: ANN001
    ack()
    open_assumption_modal(client, body["trigger_id"])


@app.action("open_drive_import_modal")
def open_drive_import_modal(ack, body, client):  # noqa: ANN001
    ack()
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "drive_import_submit",
            "title": {"type": "plain_text", "text": "Import from Drive"},
            "submit": {"type": "plain_text", "text": "Import"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "drive_link_block",
                    "label": {"type": "plain_text", "text": "Google Doc Link"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "drive_link_input",
                        "placeholder": {"type": "plain_text", "text": "Paste a Google Doc URL"},
                    },
                }
            ],
        },
    )


@app.action("open_magic_import_modal")
def open_magic_import_modal(ack, body, client):  # noqa: ANN001
    open_drive_import_modal(ack, body, client)


@app.view("drive_import_submit")
def handle_drive_import_submit(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        return
    values = body["view"]["state"]["values"]
    link = values["drive_link_block"]["drive_link_input"]["value"]
    file_id = extract_drive_file_id(link or "")
    if not file_id:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please provide a valid Google Doc link.")
        return
    token_data = db_service.get_google_token(project["id"])
    if not token_data or not token_data.get("access_token"):
        client.chat_postEphemeral(
            channel=user_id,
            user=user_id,
            text="Google Drive is not connected. Use the Connect Google Drive button first.",
        )
        return
    access_token = token_data["access_token"]
    refresh_token = token_data.get("refresh_token")
    token_expiry = token_data.get("token_expiry")
    if refresh_token and google_service.token_is_expired(token_expiry):
        try:
            refreshed = google_service.refresh_access_token(refresh_token)
            access_token = refreshed.get("access_token", access_token)
            db_service.update_google_tokens(
                project["id"],
                access_token,
                refreshed.get("refresh_token", refresh_token),
                refreshed.get("expires_in"),
            )
        except requests.exceptions.RequestException:
            logger.exception("Failed to refresh Google token")
            client.chat_postEphemeral(
                channel=user_id,
                user=user_id,
                text="Failed to refresh Google Drive access. Please reconnect Drive.",
            )
            return
    try:
        content = google_service.fetch_file_content(file_id, access_token)
    except (requests.exceptions.RequestException, ValueError):
        logger.exception("Failed to fetch Drive content")
        client.chat_postEphemeral(
            channel=user_id,
            user=user_id,
            text="Unable to fetch that document. Check the link and permissions.",
        )
        return
    assumptions = ai_extractor.extract_assumptions(content)
    saved = save_assumptions_from_text(project["id"], assumptions)
    client.chat_postEphemeral(
        channel=user_id,
        user=user_id,
        text=f"Imported {saved} assumptions from Drive.",
    )
    publish_home_tab_async(client, user_id, "roadmap:roadmap")


@app.action("open_magic_paste_modal")
def open_magic_paste_modal(ack, body, client):  # noqa: ANN001
    ack()
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "magic_paste_submit",
            "title": {"type": "plain_text", "text": "Magic Paste"},
            "submit": {"type": "plain_text", "text": "Import"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "magic_paste_block",
                    "label": {"type": "plain_text", "text": "Paste content"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "magic_paste_input",
                        "multiline": True,
                    },
                }
            ],
        },
    )


@app.view("magic_paste_submit")
def handle_magic_paste_submit(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        return
    values = body["view"]["state"]["values"]
    pasted_text = values["magic_paste_block"]["magic_paste_input"]["value"]
    if not pasted_text:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please paste some content to import.")
        return
    assumptions = ai_extractor.extract_assumptions(pasted_text)
    saved = save_assumptions_from_text(project["id"], assumptions)
    client.chat_postEphemeral(
        channel=user_id,
        user=user_id,
        text=f"Imported {saved} assumptions from your pasted content.",
    )
    publish_home_tab_async(client, user_id, "roadmap:roadmap")


@app.action("edit_assumption")
def open_edit_assumption(ack, body, client):  # noqa: ANN001
    ack()
    assumption_id = int(body["actions"][0]["value"])
    assumption = db_service.get_assumption(assumption_id)
    if not assumption:
        client.chat_postEphemeral(
            channel=body["user"]["id"],
            user=body["user"]["id"],
            text="That roadmap item could not be found.",
        )
        return
    open_edit_assumption_modal(client, body["trigger_id"], assumption)


@app.action("edit_assumption_text")
def open_edit_assumption_text(ack, body, client):  # noqa: ANN001
    ack()
    assumption_id = int(body["actions"][0]["value"])
    assumption = db_service.get_assumption(assumption_id)
    if not assumption:
        client.chat_postEphemeral(
            channel=body["user"]["id"],
            user=body["user"]["id"],
            text="That roadmap item could not be found.",
        )
        return
    open_edit_assumption_text_modal(client, body["trigger_id"], assumption)


@app.action("add_canvas_item")
def open_canvas_item_modal(ack, body, client):  # noqa: ANN001
    ack()
    section = body["actions"][0]["value"]
    client.views_open(trigger_id=body["trigger_id"], view=add_canvas_item_modal(section))


@app.action("attach_question_bank")
def attach_question_bank(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    initial_channel = project.get("channel_id") if project else None
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "insert_questions",
            "title": {"type": "plain_text", "text": "Question Bank"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Select a method to generate relevant interview questions.",
                    },
                },
                {
                    "type": "input",
                    "block_id": "method_block",
                    "label": {"type": "plain_text", "text": "Method"},
                    "element": {
                        "type": "static_select",
                        "action_id": "method_select",
                        "options": [
                            {
                                "text": {"type": "plain_text", "text": ToolkitService.DEFAULT_METHOD_NAME},
                                "value": ToolkitService.DEFAULT_METHOD_NAME,
                            },
                            {"text": {"type": "plain_text", "text": "Fake Door Follow-up"}, "value": "Fake Door"},
                            {"text": {"type": "plain_text", "text": "Concept Testing"}, "value": "Concept Testing"},
                        ],
                    },
                },
                {
                    "type": "input",
                    "block_id": "channel_select",
                    "label": {"type": "plain_text", "text": "Send to channel"},
                    "element": {
                        "type": "channels_select",
                        "action_id": "channel_input",
                        **({"initial_channel": initial_channel} if initial_channel else {}),
                    },
                },
            ],
            "submit": {"type": "plain_text", "text": "Send to Channel"},
        },
    )


@app.view("insert_questions")
def handle_insert_questions(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    values = body["view"]["state"]["values"]
    method = values.get("method_block", {}).get("method_select", {}).get("selected_option", {}).get("value")
    channel_id = values.get("channel_select", {}).get("channel_input", {}).get("selected_channel")
    questions = toolkit_service.get_question_bank(method)
    questions_text = "\n".join([f"• {question}" for question in questions])
    message = f"📋 *Suggested Questions for {method}:*\n\n{questions_text}"
    client.chat_postMessage(channel=channel_id, text=message)


@app.view("add_canvas_item_submit")
def add_canvas_item_submit(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        return
    section = body["view"]["private_metadata"]
    text = body["view"]["state"]["values"]["canvas_text"]["canvas_input"]["value"]
    db_service.add_canvas_item(project["id"], section, text, is_ai=False)
    publish_home_tab_async(client, user_id, "discovery:canvas")


@app.action("ai_autofill_canvas")
def handle_ai_canvas(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    section = body["actions"][0]["value"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        return
    channel_id = body.get("channel", {}).get("id", user_id)
    client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text=f"🧠 AI is brainstorming for '{section}'...",
    )
    context = f"{project['name']} — {project.get('description', '').strip()}"

    def generate_canvas_item() -> None:
        try:
            suggestion = ai_service.generate_canvas_suggestion(section, context)
            db_service.add_canvas_item(project["id"], section, suggestion, is_ai=True)
            publish_home_tab_async(client, user_id, "discovery:canvas")
        except Exception:  # noqa: BLE001
            logger.exception("Failed to generate canvas suggestion for %s", user_id)
            client.chat_postEphemeral(user=user_id, text=f"Sorry, I couldn't generate a suggestion for '{section}'. Please try again.")


@app.action("change_stage")
def open_change_stage(ack, body, client):  # noqa: ANN001
    ack()
    project = db_service.get_active_project(body["user"]["id"])
    if not project:
        client.chat_postEphemeral(channel=body["user"]["id"], user=body["user"]["id"], text="Please create a project first.")
        return
    client.views_open(trigger_id=body["trigger_id"], view=change_stage_modal(project["stage"]))


@app.view("change_stage_submit")
def change_stage_submit(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        return
    stage = body["view"]["state"]["values"]["stage_select"]["stage_input"]["selected_option"]["value"]
    db_service.set_project_stage(project["id"], stage)
    publish_home_tab_async(client, user_id, "experiments:framework")


@app.action("open_invite_member")
def open_invite_member(ack, body, client):  # noqa: ANN001
    ack()
    client.views_open(trigger_id=body["trigger_id"], view=invite_member_modal())


@app.view("invite_member_submit")
def invite_member_submit(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    selected_user = body["view"]["state"]["values"]["member_select"]["selected_member"]["selected_user"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        return
    added = db_service.add_project_member(project["id"], selected_user)
    if added:
        try:
            client.chat_postMessage(
                channel=selected_user,
                text=f"You're now a member of the Evidently project *{project['name']}*.",
            )
        except Exception:  # noqa: BLE001
            logger.debug("Unable to send DM to invited member.", exc_info=True)
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Teammate added to the project.")
    else:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="That teammate is already in the project.")
    publish_home_tab_async(client, user_id, "team:decision")


@app.action("open_link_channel")
def open_link_channel(ack, body, client):  # noqa: ANN001
    ack()
    client.views_open(trigger_id=body["trigger_id"], view=link_channel_modal())


@app.view("link_channel_submit")
def link_channel_submit(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        return
    channel_id = body["view"]["state"]["values"]["channel_select"]["selected_channel"]["selected_channel"]
    tabs_state = body["view"]["state"]["values"].get("tab_template", {})
    selected_tabs = [option["value"] for option in tabs_state.get("tab_options", {}).get("selected_options", [])]

    try:
        client.conversations_join(channel=channel_id)
        info = client.conversations_info(channel=channel_id)
        channel_name = info["channel"]["name"]
        db_service.set_project_channel(project["id"], channel_id)
        apply_channel_template(client, channel_id, selected_tabs)
        client.chat_postEphemeral(channel=user_id, user=user_id, text=f"Linked #{channel_name} to this project.")
        publish_home_tab_async(client, user_id, "team:integrations")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to link channel: %s", exc, exc_info=True)
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Unable to link that channel right now.")


def _set_next_active_project(user_id: str, excluded_project_id: int | None = None) -> None:
    projects = db_service.get_user_projects(user_id)
    for project in projects:
        project_id = project.get("id")
        if not project_id or (excluded_project_id and project_id == excluded_project_id):
            continue
        project_data = db_service.get_project(project_id)
        if project_data and project_data.get("status") == "active":
            db_service.set_active_project(user_id, project_id)
            return
    db_service.clear_active_project(user_id)


@app.action("open_edit_project")
@app.action("open_edit_project_modal")
def open_edit_project(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        return
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "edit_project_submit",
            "title": {"type": "plain_text", "text": "Edit Project"},
            "submit": {"type": "plain_text", "text": "Save"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "name_block",
                    "label": {"type": "plain_text", "text": "Project Name"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "name_input",
                        "initial_value": project.get("name", ""),
                    },
                },
                {
                    "type": "input",
                    "block_id": "description_block",
                    "label": {"type": "plain_text", "text": "Description"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "description_input",
                        "multiline": True,
                        "initial_value": project.get("description", ""),
                    },
                },
                {
                    "type": "input",
                    "block_id": "mission_block",
                    "label": {"type": "plain_text", "text": "Mission"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "mission_input",
                        "initial_value": project.get("mission", "") or "",
                    },
                },
            ],
        },
    )


def _handle_project_management_action(ack, body, client, action_name: str) -> None:  # noqa: ANN001
    """Helper to consolidate project management action logic."""
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        return

    if action_name == "archive":
        db_service.archive_project(project["id"])
    elif action_name == "leave":
        member_count = db_service.count_project_members(project["id"])
        if member_count <= 1:
            db_service.archive_project(project["id"])
            db_service.leave_project(project["id"], user_id)
        else:
            db_service.leave_project(project["id"], user_id)
    elif action_name == "delete":
        db_service.delete_project(project["id"])

    db_service.clear_active_project(user_id)
    publish_home_tab_hub(client, user_id)


@app.action("archive_project")
def archive_project(ack, body, client):  # noqa: ANN001
    _handle_project_management_action(ack, body, client, "archive")


@app.action("leave_project")
def leave_project(ack, body, client):  # noqa: ANN001
    _handle_project_management_action(ack, body, client, "leave")


@app.action("delete_project_confirm")
def delete_project_confirm(ack, body, client):  # noqa: ANN001
    _handle_project_management_action(ack, body, client, "delete")


@app.view("edit_project_submit")
def handle_edit_project_submit(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        return
    try:
        values = body["view"]["state"]["values"]
        name = values["name_block"]["name_input"]["value"]
        description = values["description_block"]["description_input"]["value"]
        mission = values["mission_block"]["mission_input"]["value"]
        db_service.update_project_details(project["id"], name, description, mission)
        publish_home_tab_async(client, user_id)
    except Exception:  # noqa: BLE001
        logger.error("Failed to update project details", exc_info=True)


@app.view("edit_project_submission")
def handle_edit_project_submission(ack, body, client, logger):  # noqa: ANN001
    user_id = body["user"]["id"]
    project_id = None
    try:
        project_id = int(body["view"].get("private_metadata", "0"))
    except ValueError:
        project_id = None
    if not project_id:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Unable to locate that project.")
        ack()
        return
    try:
        values = body["view"]["state"]["values"]
        name = values["name_block"]["name_input"]["value"]
        description = values["description_block"]["description_input"]["value"]
        mission = values["mission_block"]["mission_input"]["value"]
        db_service.update_project(project_id, {"name": name, "mission": mission, "description": description})
        publish_home_tab_async(client, user_id, "overview")
    except Exception:  # noqa: BLE001
        logger.error("Failed to update project details", exc_info=True)
    ack()


@app.view("magic_import_submission")
def handle_magic_import_submission(ack, body, client, logger):  # noqa: ANN001
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        ack()
        return
    try:
        values = body["view"]["state"]["values"]
        text_input = values["magic_import_block"]["magic_import_input"]["value"]
    except KeyError:
        logger.error("Magic import submission missing expected input fields.")
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please provide text to import.")
        ack()
        return
    try:
        assumptions = ai_service.extract_assumptions(text_input)
        saved = save_assumptions_from_text(project["id"], assumptions)
        client.chat_postEphemeral(
            channel=user_id,
            user=user_id,
            text=f"Imported {saved} assumptions from the magic import.",
        )
        publish_home_tab_async(client, user_id, "roadmap:roadmap")
    except Exception:  # noqa: BLE001
        logger.error("Failed to import assumptions from magic import", exc_info=True)
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Magic import failed. Please try again.")
    ack()


@app.view("invite_member_submission")
def handle_invite_member_submission(ack, body, client, logger):  # noqa: ANN001
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        ack()
        return
    selected_user = body["view"]["state"]["values"]["member_select"]["selected_member"]["selected_user"]
    try:
        added = db_service.add_project_member(project["id"], selected_user)
        if added:
            try:
                client.chat_postMessage(
                    channel=selected_user,
                    text=f"You're now a member of the Evidently project *{project['name']}*.",
                )
            except Exception:  # noqa: BLE001
                logger.debug("Unable to send DM to invited member.", exc_info=True)
            client.chat_postEphemeral(channel=user_id, user=user_id, text="Teammate added to the project.")
        else:
            client.chat_postEphemeral(channel=user_id, user=user_id, text="That teammate is already in the project.")
        publish_home_tab_async(client, user_id, "team:decision")
    except Exception:  # noqa: BLE001
        logger.error("Failed to add project member", exc_info=True)
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Unable to add that teammate right now.")
    ack()


@app.action("confirm_archive_project")
def confirm_archive_project(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        return
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "archive_project_submit",
            "private_metadata": str(project["id"]),
            "title": {"type": "plain_text", "text": "Archive Project"},
            "submit": {"type": "plain_text", "text": "Archive"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Are you sure? This will hide the project.",
                    },
                }
            ],
        },
    )


@app.view("archive_project_submit")
def handle_archive_project_submit(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    try:
        project_id = int(body["view"]["private_metadata"])
        db_service.archive_project(project_id)
        _set_next_active_project(user_id, excluded_project_id=project_id)
        publish_home_tab_async(client, user_id)
    except Exception:  # noqa: BLE001
        logger.error("Failed to archive project", exc_info=True)


@app.action("confirm_delete_project")
def confirm_delete_project(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        return
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "delete_project_submit",
            "private_metadata": str(project["id"]),
            "title": {"type": "plain_text", "text": "Delete Project"},
            "submit": {"type": "plain_text", "text": "Delete"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Are you sure? This action cannot be undone.",
                    },
                }
            ],
        },
    )


@app.view("delete_project_submit")
def handle_delete_project_submit(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    try:
        project_id = int(body["view"]["private_metadata"])
        db_service.delete_project(project_id)
        db_service.clear_active_project(user_id)
        publish_home_tab_async(client, user_id)
    except Exception:  # noqa: BLE001
        logger.error("Failed to delete project", exc_info=True)


@app.action("open_create_channel")
def open_create_channel(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        return
    client.views_open(trigger_id=body["trigger_id"], view=create_channel_modal(project["name"]))


@app.action("channel_action")
def handle_channel_action(ack):  # noqa: ANN001
    ack()


@app.view("create_channel_submit")
def create_channel_submit(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        return
    values = body["view"]["state"]["values"]
    channel_name = values["channel_name"]["channel_input"]["value"].strip().lower().replace(" ", "-")
    channel_name = re.sub(r"[^a-z0-9-_]", "", channel_name)
    members = values.get("member_select", {}).get("selected_members", {}).get("selected_users") or []
    tabs_state = values.get("tab_template", {})
    selected_tabs = [option["value"] for option in tabs_state.get("tab_options", {}).get("selected_options", [])]

    try:
        create_response = client.conversations_create(name=channel_name)
        channel_id = create_response["channel"]["id"]
        client.conversations_join(channel=channel_id)
        if members:
            client.conversations_invite(channel=channel_id, users=",".join(members))
        db_service.set_project_channel(project["id"], channel_id)
        apply_channel_template(client, channel_id, selected_tabs)
        client.chat_postMessage(
            channel=channel_id,
            text=f"Welcome to *{project['name']}*! This channel is now linked to the Evidently project.",
        )
        client.chat_postEphemeral(channel=user_id, user=user_id, text=f"Created and linked #{channel_name}.")
        publish_home_tab_async(client, user_id, "team:integrations")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to create channel: %s", exc, exc_info=True)
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Unable to create that channel right now.")


@app.action("open_extract_insights")
def open_extract_insights(ack, body, client):  # noqa: ANN001
    ack()
    client.views_open(trigger_id=body["trigger_id"], view=extract_insights_modal())


@app.view("extract_insights_submit")
def extract_insights_submit(ack, body, client, logger):  # noqa: ANN001
    ack()
    values = body["view"]["state"]["values"]
    channel_id = values["channel_select"]["channel_input"]["selected_channel"]
    message_link = values.get("message_link", {}).get("message_input", {}).get("value")
    if message_link:
        link_channel, ts = parse_message_link(message_link)
        if not link_channel or not ts:
            client.chat_postEphemeral(
                channel=body["user"]["id"],
                user=body["user"]["id"],
                text="That message link does not look valid. Try copying it again.",
            )
            return
        channel_id = link_channel
    else:
        history = client.conversations_history(channel=channel_id, limit=1)
        if not history.get("messages"):
            client.chat_postEphemeral(
                channel=body["user"]["id"],
                user=body["user"]["id"],
                text="No recent messages found in that channel.",
            )
            return
        ts = history["messages"][0]["ts"]

    run_thread_analysis(client, channel_id, ts, logger)


def _get_integration_modal_config(integration_type: str) -> tuple[str, str]:
    if integration_type == "drive":
        return "Google Drive", "Drive folder URL or ID"
    if integration_type == "asana":
        return "Asana", "Asana project URL or ID"
    if integration_type == "miro":
        return "Miro", "Miro board URL or ID"
    return "Integration", "External URL or ID"


def _open_integration_modal(client, trigger_id: str, project: dict[str, Any], integration_type: str) -> None:
    title, label = _get_integration_modal_config(integration_type)
    integrations = project.get("integrations") or {}
    existing_value = None
    if integration_type == "drive":
        existing_value = integrations.get("drive", {}).get("folder_id")
    elif integration_type == "asana":
        existing_value = integrations.get("asana", {}).get("project_id")
    elif integration_type == "miro":
        existing_value = integrations.get("miro", {}).get("board_url")

    element: dict[str, Any] = {"type": "plain_text_input", "action_id": "integration_value"}
    if existing_value:
        element["initial_value"] = existing_value

    client.views_open(
        trigger_id=trigger_id,
        view={
            "type": "modal",
            "callback_id": "integration_modal_submit",
            "private_metadata": json.dumps({"project_id": project["id"], "type": integration_type}),
            "title": {"type": "plain_text", "text": title},
            "submit": {"type": "plain_text", "text": "Save"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "integration_block",
                    "label": {"type": "plain_text", "text": label},
                    "element": element,
                }
            ],
        },
    )


@app.action("open_integration_modal_drive")
def open_integration_modal_drive(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        return
    _open_integration_modal(client, body["trigger_id"], project, "drive")


@app.action("connect_google_drive")
def connect_google_drive(ack, body, client):  # noqa: ANN001
    ack()
    _send_google_auth_link(body["user"]["id"], client)


@app.action("start_google_auth")
def start_google_auth(ack, body, client):  # noqa: ANN001
    ack()
    _send_google_auth_link(body["user"]["id"], client)


def _send_google_auth_link(user_id: str, client) -> None:  # noqa: ANN001
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        return
    try:
        state = db_service.create_oauth_state(user_id, project["id"])
        auth_url = google_service.get_auth_url(state)
    except ValueError:
        client.chat_postEphemeral(
            channel=user_id,
            user=user_id,
            text="Google OAuth is not configured. Set GOOGLE_CLIENT_ID/SECRET and GOOGLE_REDIRECT_URI.",
        )
        return
    client.chat_postEphemeral(
        channel=user_id,
        user=user_id,
        text=f"Connect your Google Drive here: {auth_url}",
    )


@app.action("open_integration_modal_asana")
def open_integration_modal_asana(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        return
    _open_integration_modal(client, body["trigger_id"], project, "asana")


@app.action("open_integration_modal_miro")
def open_integration_modal_miro(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        return
    _open_integration_modal(client, body["trigger_id"], project, "miro")


@app.view("integration_modal_submit")
def handle_integration_modal_submit(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    try:
        metadata = json.loads(body["view"]["private_metadata"] or "{}")
        project_id = int(metadata.get("project_id"))
        integration_type = metadata.get("type")
        values = body["view"]["state"]["values"]
        external_id = values["integration_block"]["integration_value"].get("value") or None
        if integration_type and project_id:
            db_service.add_integration_link(project_id, integration_type, external_id)
        publish_home_tab_async(client, user_id, "team:integrations")
    except (json.JSONDecodeError, ValueError, SQLAlchemyError):
        logger.exception("Failed to update integration settings")


@app.action("connect_drive")
def connect_drive(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        return
    folder = integration_service.create_drive_folder(project["name"])
    if folder.get("error"):
        client.chat_postEphemeral(channel=user_id, user=user_id, text=folder["error"])
        return
    db_service.add_integration_link(project["id"], "drive", folder["id"])
    client.chat_postEphemeral(
        channel=user_id,
        user=user_id,
        text=f"Drive folder created: {folder['link']}",
    )
    publish_home_tab_async(client, user_id, "team:integrations")


@app.action("connect_asana")
def connect_asana(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        return
    if not Config.ASANA_WORKSPACE_ID:
        client.chat_postEphemeral(
            channel=user_id,
            user=user_id,
            text="Asana workspace ID is missing. Set ASANA_WORKSPACE_ID to enable this.",
        )
        return
    asana_project = integration_service.create_asana_project(project["name"], Config.ASANA_WORKSPACE_ID)
    if asana_project.get("error"):
        client.chat_postEphemeral(channel=user_id, user=user_id, text=asana_project["error"])
        return
    db_service.add_integration_link(project["id"], "asana", asana_project["id"])
    client.chat_postEphemeral(
        channel=user_id,
        user=user_id,
        text=f"Asana project created: {asana_project['link']}",
    )
    publish_home_tab_async(client, user_id, "team:integrations")


def check_asana_alignment(project: dict, channel_id: str, client) -> None:  # noqa: ANN001
    integrations = project.get("integrations", {})
    asana_project_id = integrations.get("asana", {}).get("project_id")
    if not asana_project_id:
        client.chat_postMessage(channel=channel_id, text="Asana is not connected for this project.")
        return

    tasks_response = integration_service.get_asana_tasks(asana_project_id)
    if tasks_response.get("error"):
        client.chat_postMessage(channel=channel_id, text=tasks_response["error"])
        return
    task_names = [task.get("name", "") for task in tasks_response.get("tasks", [])]

    history = client.conversations_history(channel=channel_id, limit=50)
    messages = history.get("messages", [])
    conversation_text = "\n".join([message.get("text", "") for message in messages if message.get("text")])
    action_items = ai_service.extract_action_items(conversation_text) if conversation_text else []

    missing_items = []
    for item in action_items:
        if not any(item.lower() in task.lower() or task.lower() in item.lower() for task in task_names):
            missing_items.append(item)

    if not missing_items:
        client.chat_postMessage(
            channel=channel_id,
            text="✅ Asana looks aligned with recent chat.",
        )
        return

    missing_items = missing_items[:5]
    missing_items = [
        item
        if len(item) <= MAX_ASANA_PAYLOAD_ITEM_LENGTH
        else f"{item[:MAX_ASANA_PAYLOAD_ITEM_LENGTH - 1].rstrip()}…"
        for item in missing_items
    ]
    payload = json.dumps({"project_id": project["id"], "items": missing_items})
    client.chat_postMessage(
        channel=channel_id,
        text="📋 Project Alignment Check",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "I noticed we discussed these items, but they aren't in Asana yet:",
                },
            },
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join([f"• {item}" for item in missing_items])}},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Sync All to Asana"},
                        "action_id": "bulk_sync_asana",
                        "value": payload,
                        "style": "primary",
                    }
                ],
            },
        ],
    )


@app.command("/evidently-asana-check")
def handle_asana_check_command(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user_id"]
    channel_id = body["channel_id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=channel_id, user=user_id, text="Please create a project first.")
        return
    check_asana_alignment(project, channel_id, client)


@app.action("bulk_sync_asana")
def handle_bulk_sync_asana(ack, body, client, logger):  # noqa: ANN001
    ack()
    payload = json.loads(body["actions"][0]["value"])
    project = db_service.get_project(payload["project_id"])
    if not project:
        client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=body["user"]["id"],
            text="Project not found.",
        )
        return

    synced = 0
    for item in payload.get("items", []):
        asana_task = integration_service.create_asana_task(
            project_name=project["name"],
            task_name=item,
            description=f"Auto-synced from Slack: {item}",
        )
        if asana_task.get("error"):
            client.chat_postEphemeral(
                channel=body["channel"]["id"],
                user=body["user"]["id"],
                text=asana_task["error"],
            )
            continue
        if asana_task.get("link"):
            synced += 1

    client.chat_postEphemeral(
        channel=body["channel"]["id"],
        user=body["user"]["id"],
        text=f"✅ Synced {synced} items to Asana.",
    )


@app.action("export_report")
def handle_export_report(ack, body, client):  # noqa: ANN001
    ack()
    _run_export_report(body, client)


@app.action("export_report_footer")
def handle_export_report_footer(ack, body, client):  # noqa: ANN001
    ack()
    _run_export_report(body, client)


def _run_export_report(body, client) -> None:  # noqa: ANN001
    action_value = body["actions"][0].get("value", "pdf")
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        return
    if action_value == "csv":
        client.chat_postEphemeral(
            channel=user_id,
            user=user_id,
            text="📤 Generating CSV export... please wait.",
        )
        assumptions = project.get("assumptions", [])
        df = pd.DataFrame(assumptions)
        df = df.reindex(columns=["id", "title", "lane", "validation_status", "confidence_score"])
        buffer = io.BytesIO()
        buffer.write(df.to_csv(index=False).encode("utf-8"))
        buffer.seek(0)
        response = client.conversations_open(users=user_id)
        if not response.get("ok"):
            client.chat_postEphemeral(
                channel=user_id,
                user=user_id,
                text=(
                    "Could not open a direct message to send the report. "
                    f"Error: {response.get('error', 'Unknown error')}"
                ),
            )
            return
        dm_channel = response["channel"]["id"]
        client.files_upload_v2(
            channel=dm_channel,
            file=buffer,
            filename=f"{project['name'].lower().replace(' ', '-')}-assumptions.csv",
            title="Evidently Assumptions Export",
            initial_comment="Here is your assumptions export. 💾",
        )
        return
    client.chat_postEphemeral(
        channel=user_id,
        user=user_id,
        text="📄 Generating PDF report... please wait.",
    )
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(72, 750, f"Learning Report: {project['name']}")
    pdf.setFont("Helvetica", 12)
    y_position = 720
    metrics = db_service.get_metrics(project["id"])
    pdf.drawString(72, y_position, "Summary Metrics")
    y_position -= 18
    pdf.drawString(90, y_position, f"Experiments Run: {metrics['experiments']}")
    y_position -= 16
    pdf.drawString(90, y_position, f"Validated Assumptions: {metrics['validated']}")
    y_position -= 16
    pdf.drawString(90, y_position, f"Rejected Hypotheses: {metrics['rejected']}")
    y_position -= 24
    pdf.drawString(72, y_position, "Recent Experiments")
    y_position -= 18
    experiments = db_service.get_experiments(project["id"])
    if not experiments:
        pdf.drawString(90, y_position, "No experiments logged yet.")
    else:
        for experiment in experiments:
            if y_position < 72:
                pdf.showPage()
                pdf.setFont("Helvetica", 12)
                y_position = 750
            status = experiment.get("status", "Planning")
            title = experiment.get("title") or "Untitled Experiment"
            pdf.drawString(90, y_position, f"- {title} ({status})")
            y_position -= 16
    pdf.save()
    buffer.seek(0)
    response = client.conversations_open(users=user_id)
    if not response.get("ok"):
        client.chat_postEphemeral(
            channel=user_id,
            user=user_id,
            text=f"Could not open a direct message to send the report. Error: {response.get('error', 'Unknown error')}",
        )
        return
    dm_channel = response["channel"]["id"]
    client.files_upload_v2(
        channel=dm_channel,
        file=buffer,
        filename=f"{project['name'].lower().replace(' ', '-')}-report.pdf",
        title="Evidently Learning Report",
        initial_comment="Here is your generated executive report. 📄",
    )


@app.action("broadcast_update")
def handle_broadcast_update(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=body["channel"]["id"], user=user_id, text="Please create a project first.")
        return

    metrics = db_service.get_metrics(project["id"])
    leadership_channel = Config.LEADERSHIP_CHANNEL
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"📢 Innovation Update: {project['name']}"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Mission:* {project.get('mission', 'General')}"},
                {"type": "mrkdwn", "text": f"*Stage:* {project['stage']}"},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Latest Wins:*\n"
                    f"We validated {metrics.get('validated', 0)} key assumptions this week. "
                    f"The team is currently testing _'{metrics.get('latest_experiment', 'N/A')}'_."
                ),
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Blockers / Needs:*\nNeed approval for budget to proceed to Alpha."},
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"Posted by <@{user_id}> via Evidently"}],
        },
    ]

    try:
        client.chat_postMessage(channel=leadership_channel, blocks=blocks)
        client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=user_id,
            text=f"✅ Update posted to {leadership_channel}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to broadcast update", exc_info=True)
        client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=user_id,
            text=f"❌ Could not post to leadership channel: {exc}",
        )


@app.view("create_assumption_submit")
def handle_create_assumption(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    try:
        values = body["view"]["state"]["values"]
        project = db_service.get_active_project(user_id)
        if not project:
            client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
            return

        if "assumption_text" in values:
            raw_text = values["assumption_text"]["assumption_text_input"]["value"]
            extraction = ai_service.extract_structured_assumption(raw_text)
            if extraction.get("error"):
                extraction = {
                    "title": raw_text.strip(),
                    "matched_category": "1. VALUE",
                    "matched_sub_category": "General",
                    "estimated_confidence_score": 0,
                }
            title = extraction.get("title") or raw_text.strip()
            extracted_category = extraction.get("matched_category")
            extracted_sub_category = extraction.get("matched_sub_category")
            framework = playbook.get_5_pillar_framework()
            category = _match_framework_pillar(
                str(extracted_category).strip() if extracted_category else None,
                framework,
            )
            sub_category = str(extracted_sub_category).strip() if extracted_sub_category else "General"
            confidence_value = extraction.get("estimated_confidence_score", 0)
            try:
                confidence_score = int(confidence_value)
            except (TypeError, ValueError):
                confidence_score = 0
            confidence_score = max(0, min(5, confidence_score))
            similar_title = db_service.find_similar_assumption(project["id"], title)
            if similar_title:
                messenger_service.post_ephemeral(
                    channel=user_id,
                    user=user_id,
                    text=f"⚠️ This looks similar to an existing assumption: “{similar_title}”.",
                )
            db_service.create_assumption(
                project_id=project["id"],
                data={
                    "title": title,
                    "category": category,
                    "sub_category": sub_category,
                    "confidence_score": confidence_score,
                    "owner_id": user_id,
                },
            )
            category_label = str(category).split(". ", 1)[-1].title()
            sub_category_label = str(sub_category).strip().title()
            messenger_service.post_ephemeral(
                channel=user_id,
                user=user_id,
                text=(
                    "✅ I filed that under "
                    f"{category_label} -> {sub_category_label} with a confidence of {confidence_score}/5."
                ),
            )
        else:
            title = values["assumption_title"]["title_input"]["value"]
            category = values["assumption_category"]["assumption_category_select"]["selected_option"]["value"]
            lane = values["assumption_lane"]["lane_input"]["selected_option"]["value"]
            status = values["assumption_status"]["status_input"]["selected_option"]["value"]
            density_text = values["assumption_density"]["density_input"]["value"]
            evidence_link = values.get("assumption_evidence_link", {}).get("evidence_link_input", {}).get("value")
            try:
                density = max(0, int(density_text))
            except (ValueError, TypeError):
                density = 0

            similar_title = db_service.find_similar_assumption(project["id"], title)
            if similar_title:
                messenger_service.post_ephemeral(
                    channel=user_id,
                    user=user_id,
                    text=f"⚠️ This looks similar to an existing assumption: “{similar_title}”.",
                )

            db_service.create_assumption(
                project_id=project["id"],
                data={
                    "title": title,
                    "category": category,
                    "evidence_link": evidence_link,
                    "lane": lane,
                    "validation_status": status,
                    "status": status,
                    "evidence_density": density,
                    "owner_id": user_id,
                },
            )
        publish_home_tab_async(client, user_id, "roadmap:roadmap")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to create assumption: %s", exc, exc_info=True)


@app.view("edit_assumption_submit")
def handle_edit_assumption_submit(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    assumption_id = int(body["view"]["private_metadata"])
    try:
        values = body["view"]["state"]["values"]
        title = values["assumption_title"]["title_input"]["value"]
        lane = values["assumption_lane"]["lane_input"]["selected_option"]["value"]
        status = values["assumption_status"]["status_input"]["selected_option"]["value"]
        density_text = values["assumption_density"]["density_input"]["value"]
        try:
            density = max(0, int(density_text))
        except (ValueError, TypeError):
            density = 0

        db_service.update_assumption(
            assumption_id,
            {
                "title": title,
                "lane": lane,
                "validation_status": status,
                "evidence_density": density,
            },
        )
        publish_home_tab_async(client, user_id, "roadmap:roadmap")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to update assumption: %s", exc, exc_info=True)


@app.view("edit_assumption_text_submit")
def handle_edit_assumption_text_submit(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    assumption_id = int(body["view"]["private_metadata"])
    try:
        values = body["view"]["state"]["values"]
        title = values["assumption_text"]["text_input"]["value"]
        db_service.update_assumption_title(assumption_id, title)
        publish_home_tab_async(client, user_id, "roadmap:roadmap")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to update assumption text: %s", exc, exc_info=True)


@app.action("design_experiment")
def open_experiment_browser(ack, body, client):  # noqa: ANN001
    ack()
    value = body["actions"][0]["value"]
    if ":" in value:
        assumption_id, category = value.split(":", 1)
    else:
        assumption_id, category = value, "desirability"
    recommendations = playbook.get_recommendations(category)

    blocks = [
        NestaUI.header("📖 Test & Learn Playbook"),
        NestaUI.section(
            f"Based on your assumption category (*{category}*), here are recommended methods from the Nesta Playbook:"
        ),
        NestaUI.divider(),
    ]

    if not recommendations:
        blocks.append(NestaUI.section("No methods found for this category yet."))
    else:
        for method in recommendations:
            blocks.extend(NestaUI.method_card(method))
            tip = method.get("nesta_tip")
            if tip:
                blocks.append(NestaUI.tip_panel(tip))
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": f"Select {method['name']}"},
                            "value": f"{assumption_id}:{method['id']}",
                            "action_id": "confirm_experiment_method",
                        }
                    ],
                }
            )
            blocks.append(NestaUI.divider())

    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "title": {"type": "plain_text", "text": "Select Method"},
            "blocks": blocks,
        },
    )


@app.action("confirm_experiment_method")
def confirm_experiment_method(ack, body, client):  # noqa: ANN001
    ack()
    assumption_id, method_id = body["actions"][0]["value"].split(":")
    method = playbook.get_method_details(method_id)
    method_name = method["name"] if method else method_id
    client.chat_postEphemeral(
        channel=body["user"]["id"],
        user=body["user"]["id"],
        text=f"✅ Selected {method_name} for assumption {assumption_id}.",
    )

    tip = playbook.get_random_tip()
    client.chat_postMessage(
        channel=body["user"]["id"],
        blocks=[NestaUI.tip_panel(tip)],
        text=f"Nesta tip: {tip}",
    )


@app.action("ai_recommend_experiments")
def handle_ai_experiments(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
        return
    context = f"Project: {project['name']}\nStage: {project['stage']}\nCanvas: {project.get('canvas_items', [])}"

    loading_blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "AI is drafting experiment suggestions...",
            },
        }
    ]
    response = client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "title": {"type": "plain_text", "text": "AI Suggestions"},
            "close": {"type": "plain_text", "text": "Close"},
            "blocks": loading_blocks,
        },
    )
    view_id = response["view"]["id"]

    def update_view() -> None:
        suggestions = ai_service.generate_experiment_suggestions(context)
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "AI recommended experiments based on your current context:",
                },
            },
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": suggestions}},
        ]
        client.views_update(
            view_id=view_id,
            view={
                "type": "modal",
                "title": {"type": "plain_text", "text": "AI Suggestions"},
                "close": {"type": "plain_text", "text": "Close"},
                "blocks": blocks,
            },
        )

    run_in_background(update_view)


@app.action("open_create_experiment_modal")
def open_create_experiment_modal(ack, body, client):  # noqa: ANN001
    ack()
    _open_create_experiment_modal(client, body["trigger_id"])


@app.action("log_experiment_for_assumption")
def log_experiment_for_assumption(ack, body, client, logger):  # noqa: ANN001
    ack()
    assumption_id = int(body["actions"][0]["value"])
    assumption = db_service.get_assumption(assumption_id)
    if not assumption:
        client.chat_postEphemeral(channel=body["user"]["id"], user=body["user"]["id"], text="Assumption not found.")
        return
    phase = assumption.get("test_and_learn_phase", "define")
    recommendation = ai_service.recommend_playbook_method(phase, assumption.get("title", ""), playbook.methods)
    method_id = recommendation.get("method_id") if isinstance(recommendation, dict) else None
    method = playbook.get_method_details(method_id) if method_id else None
    initial_method = method.get("name") if method else None
    suggestion_note = None
    if initial_method:
        reason = recommendation.get("reason", "matches the current phase")
        suggestion_note = f"Pre-selected: *{initial_method}* because {reason}."
    _open_create_experiment_modal(
        client,
        body["trigger_id"],
        initial_method=initial_method,
        assumption_id=assumption_id,
        suggestion_note=suggestion_note,
    )


@app.action("create_experiment_manual")
def open_manual_experiment_modal(ack, body, client):  # noqa: ANN001
    ack()
    _open_create_experiment_modal(client, body["trigger_id"])


def _open_create_experiment_modal(
    client,
    trigger_id: str,
    initial_method: str | None = None,
    assumption_id: int | None = None,
    suggestion_note: str | None = None,
) -> None:  # noqa: ANN001
    method_options = [
        {"text": {"type": "plain_text", "text": "Fake Door"}, "value": "Fake Door"},
        {
            "text": {"type": "plain_text", "text": ToolkitService.DEFAULT_METHOD_NAME},
            "value": ToolkitService.DEFAULT_METHOD_NAME,
        },
        {"text": {"type": "plain_text", "text": "A/B Test"}, "value": "A/B Test"},
        {"text": {"type": "plain_text", "text": "Concierge MVP"}, "value": "Concierge MVP"},
    ]
    for method_data in playbook.methods.values():
        method_name = method_data.get("name")
        if not method_name:
            continue
        if any(option["value"] == method_name for option in method_options):
            continue
        method_options.append({"text": {"type": "plain_text", "text": method_name}, "value": method_name})
    initial_option = next(
        (option for option in method_options if option["value"] == initial_method),
        None,
    )
    blocks = []
    if suggestion_note:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": suggestion_note}]})
    blocks.extend(
        [
            {
                "type": "input",
                "block_id": "title_block",
                "label": {"type": "plain_text", "text": "Experiment Title"},
                "element": {"type": "plain_text_input", "action_id": "title"},
            },
            {
                "type": "input",
                "block_id": "method_block",
                "label": {"type": "plain_text", "text": "Method"},
                "element": {
                    "type": "static_select",
                    "action_id": "method",
                    "options": method_options,
                    "initial_option": initial_option,
                },
            },
            {
                "type": "input",
                "block_id": "hypothesis_block",
                "label": {"type": "plain_text", "text": "Hypothesis"},
                "element": {"type": "plain_text_input", "action_id": "hypothesis", "multiline": True},
            },
        ]
    )
    client.views_open(
        trigger_id=trigger_id,
        view={
            "type": "modal",
            "callback_id": "create_experiment_submit",
            "private_metadata": str(assumption_id) if assumption_id else "",
            "title": {"type": "plain_text", "text": "New Experiment"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": blocks,
            "submit": {"type": "plain_text", "text": "Launch Experiment"},
        },
    )


@app.view("create_experiment_submit")
def handle_create_experiment(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    try:
        values = body["view"]["state"]["values"]
        title = values["title_block"]["title"]["value"]
        method = values["method_block"]["method"]["selected_option"]["value"]
        hypothesis = values["hypothesis_block"]["hypothesis"]["value"]
        assumption_id_value = (body["view"].get("private_metadata") or "").strip()
        assumption_id = int(assumption_id_value) if assumption_id_value else None

        project = db_service.get_active_project(user_id)
        if not project:
            client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
            return

        db_service.create_experiment(
            project_id=project["id"],
            title=title,
            method=method,
            hypothesis=hypothesis,
            assumption_id=assumption_id,
        )
        if project.get("channel_id"):
            client.chat_postMessage(
                channel=project["channel_id"],
                text=f"🧪 *New Experiment Created: {title}*\n_{hypothesis}_",
                blocks=[
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"🧪 *New Experiment Created: {title}*"},
                    },
                    {
                        "type": "context",
                        "elements": [
                            {"type": "mrkdwn", "text": f"Method: {method} | Owner: <@{user_id}>"}
                        ],
                    },
                ],
            )
        publish_home_tab_async(client, user_id, "experiments:active")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to create experiment: %s", exc, exc_info=True)


def open_update_experiment_modal(client, trigger_id: str, experiment: dict) -> None:  # noqa: ANN001
    status_options = [
        {"text": {"type": "plain_text", "text": "Planning"}, "value": "Planning"},
        {"text": {"type": "plain_text", "text": "🟢 Live"}, "value": "Live"},
        {"text": {"type": "plain_text", "text": "✅ Completed"}, "value": "Completed"},
        {"text": {"type": "plain_text", "text": "🛑 Paused"}, "value": "Paused"},
        {"text": {"type": "plain_text", "text": "📦 Archived"}, "value": "Archived"},
    ]
    status_option = next(
        (option for option in status_options if option["value"] == experiment.get("status")),
        None,
    )

    client.views_open(
        trigger_id=trigger_id,
        view={
            "type": "modal",
            "callback_id": "update_experiment_submit",
            "private_metadata": str(experiment["id"]),
            "title": {"type": "plain_text", "text": "Update Status"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "title_block",
                    "label": {"type": "plain_text", "text": "Title"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "title_input",
                        "initial_value": experiment.get("title") or "",
                    },
                },
                {
                    "type": "input",
                    "block_id": "hypothesis_block",
                    "label": {"type": "plain_text", "text": "Hypothesis"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "hypothesis_input",
                        "multiline": True,
                        "initial_value": experiment.get("hypothesis") or "",
                    },
                },
                {
                    "type": "input",
                    "block_id": "status_block",
                    "label": {"type": "plain_text", "text": "Current Status"},
                    "element": {
                        "type": "static_select",
                        "action_id": "status",
                        "options": status_options,
                        "initial_option": status_option or status_options[0],
                    },
                },
                {
                    "type": "input",
                    "block_id": "kpi_block",
                    "label": {"type": "plain_text", "text": "Current KPI Value (Optional)"},
                    "optional": True,
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "kpi_value",
                        "initial_value": experiment.get("current_value") or "",
                    },
                },
            ],
            "submit": {"type": "plain_text", "text": "Update"},
        },
    )


@app.action("update_experiment")
def open_update_experiment_modal_action(ack, body, client):  # noqa: ANN001
    ack()
    experiment_id = int(body["actions"][0]["value"])
    experiment = db_service.get_experiment(experiment_id)
    if not experiment:
        client.chat_postEphemeral(
            channel=body["user"]["id"],
            user=body["user"]["id"],
            text="That experiment could not be found.",
        )
        return
    open_update_experiment_modal(client, body["trigger_id"], experiment)


@app.action("delete_experiment")
def delete_experiment(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    experiment_id = int(body["actions"][0]["value"])
    experiment = db_service.get_experiment(experiment_id)
    if not experiment:
        client.chat_postEphemeral(
            channel=user_id,
            user=user_id,
            text="That experiment could not be found.",
        )
        return
    db_service.delete_experiment(experiment_id)
    publish_home_tab_async(client, user_id)


ASANA_DATASET_LINK_PREFIX = "asana:"


def _sync_experiment_to_asana(
    client: "WebClient",
    user_id: str,
    project: dict,
    experiment: dict,
    channel_id: str,
) -> bool:
    description = (
        f"Hypothesis: {experiment.get('hypothesis', '—')}\n"
        f"Method: {experiment.get('method', '—')}\n"
        f"Current KPI: {experiment.get('primary_kpi', '—')}"
    )
    asana_task = integration_service.create_asana_task(
        project_name=project["name"],
        task_name=experiment.get("title", "Experiment"),
        description=description,
    )
    if asana_task.get("error"):
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=asana_task["error"],
        )
        return False
    if asana_task.get("task_id"):
        db_service.update_experiment(
            experiment["id"],
            data={"dataset_link": f"{ASANA_DATASET_LINK_PREFIX}{asana_task['task_id']}"},
        )
    if asana_task.get("link"):
        client.chat_postMessage(
            channel=channel_id,
            text=f"✅ Synced to Asana: <{asana_task['link']}|View Task>",
        )
    return True


@app.view("update_experiment_submit")
def handle_update_experiment_submit(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    experiment_id = int(body["view"]["private_metadata"])
    try:
        values = body["view"]["state"]["values"]
        title = values["title_block"]["title_input"]["value"]
        hypothesis = values["hypothesis_block"]["hypothesis_input"]["value"]
        status = values["status_block"]["status"]["selected_option"]["value"]
        kpi_value = values.get("kpi_block", {}).get("kpi_value", {}).get("value")

        db_service.update_experiment(
            experiment_id,
            data={"title": title, "hypothesis": hypothesis},
            status=status,
            kpi=kpi_value,
        )
        project = db_service.get_active_project(user_id)
        if project and project.get("channel_id"):
            status_emoji = {"Live": "🟢", "Completed": "✅", "Paused": "🛑"}.get(status, "🔵")
            client.chat_postMessage(
                channel=project["channel_id"],
                text=f"{status_emoji} *Experiment Update: {status}*",
            )
            if status == "Live":
                experiment = db_service.get_experiment(experiment_id)
                if experiment:
                    _sync_experiment_to_asana(
                        client,
                        user_id,
                        project,
                        experiment,
                        project["channel_id"],
                    )
        publish_home_tab_async(client, user_id, "experiments:active")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to update experiment: %s", exc, exc_info=True)


@app.action("experiment_overflow")
def handle_experiment_overflow(ack, body, client):  # noqa: ANN001
    ack()
    selection = body["actions"][0]["selected_option"]["value"]
    action_type, experiment_id = selection.split(":", 1)
    experiment = db_service.get_experiment(int(experiment_id))
    if not experiment:
        client.chat_postEphemeral(
            channel=body["user"]["id"],
            user=body["user"]["id"],
            text="That experiment could not be found.",
        )
        return

    if action_type == "edit":
        open_update_experiment_modal(client, body["trigger_id"], experiment)
        return
    if action_type == "archive":
        db_service.update_experiment(experiment["id"], status="Archived")
        client.chat_postMessage(
            channel=body["channel"]["id"],
            text=f"📦 Archived experiment: {experiment.get('title', 'Untitled')}.",
        )
        return
    if action_type == "sync":
        project = db_service.get_active_project(body["user"]["id"])
        if not project:
            client.chat_postEphemeral(
                channel=body["channel"]["id"],
                user=body["user"]["id"],
                text="Please create a project first.",
            )
            return
        _sync_experiment_to_asana(
            client,
            body["user"]["id"],
            project,
            experiment,
            body["channel"]["id"],
        )


@app.action("draft_experiment_from_chat")
def handle_draft_experiment_from_chat(ack, body, client):  # noqa: ANN001
    ack()
    hypothesis_text = body["actions"][0]["value"]
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "create_experiment_submit",
            "title": {"type": "plain_text", "text": "New Experiment"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "title_block",
                    "label": {"type": "plain_text", "text": "Experiment Title"},
                    "element": {"type": "plain_text_input", "action_id": "title"},
                },
                {
                    "type": "input",
                    "block_id": "method_block",
                    "label": {"type": "plain_text", "text": "Method"},
                    "element": {
                        "type": "static_select",
                        "action_id": "method",
                        "options": [
                            {"text": {"type": "plain_text", "text": "Fake Door"}, "value": "Fake Door"},
                            {
                                "text": {"type": "plain_text", "text": ToolkitService.DEFAULT_METHOD_NAME},
                                "value": ToolkitService.DEFAULT_METHOD_NAME,
                            },
                            {"text": {"type": "plain_text", "text": "A/B Test"}, "value": "A/B Test"},
                            {"text": {"type": "plain_text", "text": "Concierge MVP"}, "value": "Concierge MVP"},
                        ],
                    },
                },
                {
                    "type": "input",
                    "block_id": "hypothesis_block",
                    "label": {"type": "plain_text", "text": "Hypothesis"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "hypothesis",
                        "multiline": True,
                        "initial_value": hypothesis_text,
                    },
                },
            ],
            "submit": {"type": "plain_text", "text": "Launch Experiment"},
        },
    )


@app.event("message")
def passive_listener(event, client, logger):  # noqa: ANN001
    if event.get("subtype") or event.get("bot_id"):
        return
    text = event.get("text", "").lower()
    if not text:
        return
    if "we should test" in text or "hypothesis" in text:
        client.chat_postEphemeral(
            channel=event["channel"],
            user=event["user"],
            text="🕵️ I detected a new hypothesis!",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            "It sounds like you're formulating a new test. "
                            "Want me to add this to the *Experiment Board*?"
                        ),
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Draft Experiment"},
                            "value": event.get("text", "")[:1900],
                            "action_id": "draft_experiment_from_chat",
                        }
                    ],
                },
            ],
        )


# --- 2. 'SO WHAT?' AI SUMMARISER WITH LIVE STATUS ---
@app.event("member_joined_channel")
def handle_channel_join(event, say, client, logger):  # noqa: ANN001
    """Greets the channel when the bot is added."""
    try:
        bot_id = client.auth_test()["user_id"]
        if event["user"] == bot_id:
            say(
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": WELCOME_GREETING,
                        },
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": WELCOME_USAGE,
                        },
                    },
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Open Dashboard"},
                                "action_id": "refresh_home",
                                "style": "primary",
                            }
                        ],
                    },
                ],
                text="Hi! I'm ready to help analyse your conversations.",
            )
    except Exception as exc:  # noqa: BLE001
        logger.error("Error handling channel join: %s", exc, exc_info=True)


@app.event("app_mention")
def handle_mention(body, say, client, logger):  # noqa: ANN001
    event = body["event"]
    thread_ts = event.get("thread_ts", event["ts"])
    channel_id = event["channel"]
    run_thread_analysis(client, channel_id, thread_ts, logger)


@app.shortcut("extract_insights")
def handle_extract_insights_shortcut(ack, body, client, logger):  # noqa: ANN001
    ack()
    message = body.get("message")
    if not message:
        client.views_open(trigger_id=body["trigger_id"], view=extract_insights_modal())
        return

    loading_view = client.views_open(trigger_id=body["trigger_id"], view=get_loading_modal())
    view_id = loading_view["view"]["id"]

    channel_id = body["channel"]["id"]
    thread_ts = message.get("thread_ts", message["ts"])

    def run_analysis() -> None:
        try:
            history = client.conversations_replies(channel=channel_id, ts=thread_ts)
            messages = history["messages"]
            full_text = "\n".join([f"{m.get('user', 'User')}: {m.get('text')}" for m in messages])

            attachments = [
                {"name": file.get("name"), "mimetype": file.get("mimetype")}
                for message in messages
                for file in message.get("files", []) or []
            ]

            analysis = ai_service.analyze_thread_structured(full_text, attachments)

            if analysis.get("error"):
                client.views_update(
                    view_id=view_id,
                    view={
                        "type": "modal",
                        "title": {"type": "plain_text", "text": "Error"},
                        "close": {"type": "plain_text", "text": "Close"},
                        "blocks": error_block("The AI brain is briefly offline. Please try again."),
                    },
                )
                return

            client.views_update(
                view_id=view_id,
                view={
                    "type": "modal",
                    "callback_id": "extract_insights_results",
                    "title": {"type": "plain_text", "text": "AI Insights"},
                    "close": {"type": "plain_text", "text": "Close"},
                    "blocks": get_ai_summary_block(analysis),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Error handling extract insights shortcut: %s", exc, exc_info=True)
            client.views_update(
                view_id=view_id,
                view={
                    "type": "modal",
                    "title": {"type": "plain_text", "text": "Error"},
                    "close": {"type": "plain_text", "text": "Close"},
                    "blocks": [
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": f"❌ *Something went wrong:*\n{str(exc)}"},
                        }
                    ],
                },
            )

    analysis_thread = threading.Thread(target=run_analysis, daemon=True)
    analysis_thread.start()

# --- 3. ACTIVE PERSISTENCE / NUDGES ---
@app.action("nudge_action")
def handle_nudge_action(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    action_value = body["actions"][0]["value"]

    try:
        action_type, assumption_id = action_value.split("_", 1)

        if action_type == "gen":
            client.chat_postEphemeral(
                channel=body["channel_id"],
                user=user_id,
                text=f"Generating experiment for assumption {assumption_id}...",
            )
        elif action_type == "val":
            db_service.update_assumption_validation_status(int(assumption_id), "Validated")
            client.chat_postEphemeral(
                channel=body["channel_id"], user=user_id, text=f"Assumption {assumption_id} marked as validated."
            )
        elif action_type == "arch":
            db_service.update_assumption_validation_status(int(assumption_id), "Rejected")
            client.chat_postEphemeral(
                channel=body["channel_id"], user=user_id, text=f"Assumption {assumption_id} archived."
            )
        else:
            client.chat_postEphemeral(channel=body["channel_id"], user=user_id, text="Unknown action type.")
    except Exception as exc:  # noqa: BLE001
        logger.error("Error handling nudge action for user %s: %s", user_id, exc, exc_info=True)
        client.chat_postEphemeral(
            channel=body.get("channel_id"), user=user_id, text="An error occurred while processing your request."
        )


@app.action("keep_assumption")
def handle_keep(ack, body, client, logger):  # noqa: ANN001
    ack()
    try:
        user_id = body["user"]["id"]
        assumption_id = body["actions"][0]["value"]
        db_service.update_assumption_validation_status(int(assumption_id), "Validated")
        client.chat_postMessage(channel=user_id, text=f"✅ Assumption {assumption_id} marked as validated.")
    except Exception as exc:  # noqa: BLE001
        logger.error("Error in handle_keep action: %s", exc, exc_info=True)


@app.action("validate_assumption")
def handle_validate_assumption(ack, body, client, logger):  # noqa: ANN001
    ack()
    try:
        user_id = body["user"]["id"]
        assumption_id = body["actions"][0]["value"]
        db_service.update_assumption_validation_status(int(assumption_id), "Validated")
        client.chat_postMessage(channel=user_id, text=f"✅ Assumption {assumption_id} marked as validated.")
    except Exception as exc:  # noqa: BLE001
        logger.error("Error in handle_mark_validated action: %s", exc, exc_info=True)


@app.action("keep_testing")
def handle_keep_testing(ack, body, client, logger):  # noqa: ANN001
    ack()
    try:
        user_id = body["user"]["id"]
        assumption_id = body["actions"][0]["value"]
        db_service.touch_assumption(int(assumption_id))
        client.chat_postMessage(channel=user_id, text=f"🔄 Assumption {assumption_id} is still in testing.")
    except Exception as exc:  # noqa: BLE001
        logger.error("Error in handle_keep_testing action: %s", exc, exc_info=True)


@app.action("archive_assumption")
def handle_archive(ack, body, client, logger):  # noqa: ANN001
    ack()
    try:
        user_id = body["user"]["id"]
        assumption_id = body["actions"][0]["value"]
        db_service.update_assumption_validation_status(int(assumption_id), "Rejected")
        client.chat_postMessage(channel=user_id, text=f"🗑️ Assumption {assumption_id} marked as rejected.")
    except Exception as exc:  # noqa: BLE001
        logger.error("Error in handle_archive action: %s", exc, exc_info=True)


@app.action("gen_experiment_modal")
def handle_gen_experiment(ack, body, client, logger):  # noqa: ANN001
    ack()
    try:
        assumption_text = body["actions"][0]["value"]
        trigger_id = body["trigger_id"]
        loading_view = experiment_modal(assumption_text, "Generating suggestions...")
        response = client.views_open(trigger_id=trigger_id, view=loading_view)
        view_id = response["view"]["id"]

        def update_modal() -> None:
            suggestions = ai_service.generate_experiment_suggestions(assumption_text)
            client.views_update(view_id=view_id, view=experiment_modal(assumption_text, suggestions))

        run_in_background(update_modal)
    except Exception as exc:  # noqa: BLE001
        logger.error("Error in handle_gen_experiment action: %s", exc, exc_info=True)


# --- 5. DECISION ROOM ---
@app.action("trigger_decision_room")
def open_decision_room(ack, body, client):  # noqa: ANN001
    ack()
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "start_decision_submit",
            "title": {"type": "plain_text", "text": "Start Decision Room"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Pick a channel to host the scoring session. If you don't see it, link a channel from the Home tab first.",
                    },
                },
                {
                    "type": "input",
                    "block_id": "channel_select",
                    "element": {"type": "channels_select", "action_id": "selected_channel"},
                    "label": {"type": "plain_text", "text": "Channel"},
                },
            ],
            "submit": {"type": "plain_text", "text": "Start Scoring"},
        },
    )


@app.view("start_decision_submit")
def start_decision_room(ack, body, client, view):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    channel_id = view["state"]["values"]["channel_select"]["selected_channel"]["selected_channel"]

    success, message, _session_id = decision_service.start_session(
        channel_id,
        client=client,
        user_id=user_id,
    )
    if not success:
        client.chat_postEphemeral(channel=user_id, user=user_id, text=f"❌ {message}")


@app.action("open_silent_score")
def open_silent_score(ack, body, client):  # noqa: ANN001
    ack()
    session_id, assumption_id = body["actions"][0]["value"].split(":")
    assumption = db_service.get_assumption(int(assumption_id))
    if not assumption:
        client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=body["user"]["id"],
            text="Assumption not found.",
        )
        return
    client.views_open(
        trigger_id=body["trigger_id"],
        view=silent_scoring_modal(assumption["title"], int(session_id), int(assumption_id)),
    )


@app.view("submit_silent_score")
def submit_silent_score(ack, body, view, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    try:
        session_id_str, assumption_id_str = view["private_metadata"].split(":")
        session_id = int(session_id_str)
        assumption_id = int(assumption_id_str)
        values = view["state"]["values"]
        impact = int(values["impact_block"]["impact_score"]["selected_option"]["value"])
        uncertainty = int(values["uncertainty_block"]["uncertainty_score"]["selected_option"]["value"])
        feasibility = int(values["feasibility_block"]["feasibility_score"]["selected_option"]["value"])
        confidence = int(values["evidence_block"]["confidence_score"]["selected_option"]["value"])
        rationale = values.get("rationale_block", {}).get("rationale_text", {}).get("value")

        db_service.record_decision_score(
            session_id=session_id,
            assumption_id=assumption_id,
            user_id=user_id,
            impact=impact,
            uncertainty=uncertainty,
            feasibility=feasibility,
            confidence=confidence,
            rationale=rationale,
        )

        client.chat_postMessage(channel=user_id, text="✅ Your silent score has been saved.")
    except (KeyError, ValueError) as exc:
        logger.error("Error parsing silent score submission for user %s: %s", user_id, exc, exc_info=True)
        client.chat_postEphemeral(
            channel=user_id,
            user=user_id,
            text="❌ There was an error processing your score. Please try again.",
        )


@app.action("end_decision_session")
def end_session(ack, body, client):  # noqa: ANN001
    ack()
    session_id = body["actions"][0]["value"]
    results = decision_service.reveal_scores(int(session_id))

    text = "*🏁 Silent Scoring Complete!*\n\n"
    summary_lines = []
    for assumption_id, scores in results.items():
        disagreement = "⚠️ High disagreement" if scores["disagreement"] else "✅ Consensus"
        summary_lines.append(
            (
                f"• Assumption {assumption_id}: "
                f"Impact {scores['avg_impact']:.1f}, "
                f"Uncertainty {scores['avg_uncertainty']:.1f}, "
                f"Feasibility {scores['avg_feasibility']:.1f}, "
                f"Evidence {scores['avg_confidence']:.0f} "
                f"({scores['count']} scores) — {disagreement}"
            )
        )
    text += "\n".join(summary_lines) if summary_lines else "No scores were submitted."

    client.chat_postMessage(channel=body["channel"]["id"], text=text)


# --- 6. METHODS AND CASE STUDIES ---
@app.command("/evidently-vote")
def handle_evidently_vote(ack, body, client, respond, logger):  # noqa: ANN001
    ack()
    try:
        text = (body.get("text") or "").strip()
        if not text or not text.isdigit():
            respond("Please provide an assumption ID. Example: `/evidently-vote 12`")
            return
        assumption_id = int(text)
        assumption = db_service.get_assumption(assumption_id)
        if not assumption:
            respond(f"Assumption {assumption_id} not found.")
            return
        client.views_open(
            trigger_id=body["trigger_id"],
            view=decision_vote_modal(
                assumption_title=assumption.get("title", "Untitled"),
                assumption_id=assumption_id,
                channel_id=body["channel_id"],
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to open decision vote modal", exc_info=True)
        respond("Unable to start voting right now.")


@app.view("submit_decision_vote")
def submit_decision_vote(ack, body, view, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    try:
        assumption_id_str, channel_id = view["private_metadata"].split(":", 1)
        assumption_id = int(assumption_id_str)
        values = view["state"]["values"]
        impact = int(values["impact_block"]["impact_score"]["selected_option"]["value"])
        uncertainty = int(values["uncertainty_block"]["uncertainty_score"]["selected_option"]["value"])
        decision_service.record_vote(
            assumption_id=assumption_id,
            user_id=user_id,
            impact_score=impact,
            uncertainty_score=uncertainty,
        )
        summary = decision_service.reveal_results(assumption_id)
        if summary.get("avg_uncertainty", 0) >= UNCERTAINTY_HORIZON_NOW_THRESHOLD:
            db_service.update_assumption_horizon(assumption_id, "now")
        elif summary.get("avg_uncertainty", 0) <= UNCERTAINTY_HORIZON_LATER_THRESHOLD:
            db_service.update_assumption_horizon(assumption_id, "later")
        heatmap = decision_heatmap_label(summary["avg_impact"], summary["avg_uncertainty"])
        client.chat_postMessage(
            channel=channel_id,
            text=(
                f"🗳️ Decision Room update for Assumption {assumption_id}\n"
                f"Avg Impact: {summary['avg_impact']:.2f} | "
                f"Avg Uncertainty: {summary['avg_uncertainty']:.2f}\n"
                f"{heatmap}"
            ),
            blocks=summary.get("blocks"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to submit decision vote", exc_info=True)
        client.chat_postEphemeral(
            channel=user_id,
            user=user_id,
            text="❌ Unable to record your vote right now.",
        )


@app.command("/evidently-methods")
def handle_methods(ack, body, respond, logger):  # noqa: ANN001
    ack()
    stage = (body.get("text") or "").strip().lower() or "define"
    try:
        respond(text="Generating method recommendations...", response_type="ephemeral")

        def send_response() -> None:
            narrative = ai_service.recommend_methods(stage, "")
            blocks = method_cards(stage)
            respond(text=narrative, blocks=blocks, response_type="ephemeral", replace_original=True)

        run_in_background(send_response)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to handle methods command", exc_info=True)
        respond("Unable to share methods right now.")


@app.action("view_case_study")
def open_case_study(ack, body, client, logger):  # noqa: ANN001
    ack()
    try:
        method = body["actions"][0]["value"]
        trigger_id = body.get("trigger_id")
        client.views_open(trigger_id=trigger_id, view=case_study_modal(method))
    except Exception as exc:  # noqa: BLE001
        logger.error("Error opening case study modal", exc_info=True)


@app.action("assumption_overflow")
def handle_assumption_overflow(ack, body, client, logger):  # noqa: ANN001
    ack()
    try:
        action_value = body["actions"][0]["selected_option"]["value"]
        assumption_id, action = action_value.split(":", 1)
        user_id = body["user"]["id"]

        if action in {"Now", "Next", "Later"}:
            horizon = action.lower()
            db_service.update_assumption_lane(int(assumption_id), action)
            db_service.update_assumption_horizon(int(assumption_id), horizon)
            client.chat_postEphemeral(channel=user_id, user=user_id, text=f"Moved to {action}.")
        elif action == "delete":
            db_service.delete_assumption(int(assumption_id))
            client.chat_postEphemeral(channel=user_id, user=user_id, text="Assumption deleted.")
            publish_home_tab_async(client, user_id, "roadmap:roadmap")
        elif action == "archive":
            db_service.update_assumption_validation_status(int(assumption_id), "Rejected")
            client.chat_postEphemeral(channel=user_id, user=user_id, text="Assumption archived.")
            publish_home_tab_async(client, user_id, "roadmap:roadmap")
        elif action == "edit_text":
            assumption = db_service.get_assumption(int(assumption_id))
            if not assumption:
                client.chat_postEphemeral(channel=user_id, user=user_id, text="Assumption not found.")
                return
            open_edit_assumption_text_modal(client, body["trigger_id"], assumption)
        elif action == "move":
            options = [
                {"text": {"type": "plain_text", "text": "Now"}, "value": "Now"},
                {"text": {"type": "plain_text", "text": "Next"}, "value": "Next"},
                {"text": {"type": "plain_text", "text": "Later"}, "value": "Later"},
            ]
            client.views_open(
                trigger_id=body["trigger_id"],
                view={
                    "type": "modal",
                    "callback_id": "move_assumption_submit",
                    "private_metadata": assumption_id,
                    "title": {"type": "plain_text", "text": "Move Assumption"},
                    "submit": {"type": "plain_text", "text": "Move"},
                    "close": {"type": "plain_text", "text": "Cancel"},
                    "blocks": [
                        {
                            "type": "input",
                            "block_id": "lane_block",
                            "label": {"type": "plain_text", "text": "Select lane"},
                            "element": {
                                "type": "static_select",
                                "action_id": "lane",
                                "options": options,
                            },
                        }
                    ],
                },
            )
        elif action == "exp":
            assumption = db_service.get_assumption(int(assumption_id))
            if not assumption:
                client.chat_postEphemeral(channel=user_id, user=user_id, text="Assumption not found.")
                return
            trigger_id = body.get("trigger_id")
            response = client.views_open(
                trigger_id=trigger_id,
                view=experiment_modal(assumption["title"], "Generating suggestions..."),
            )
            view_id = response["view"]["id"]

            def update_modal() -> None:
                suggestions = ai_service.generate_experiment_suggestions(assumption["title"])
                client.views_update(view_id=view_id, view=experiment_modal(assumption["title"], suggestions))

            run_in_background(update_modal)
        else:
            client.chat_postEphemeral(channel=user_id, user=user_id, text="Action received.")
    except Exception as exc:  # noqa: BLE001
        logger.error("Overflow action failed", exc_info=True)


@app.action("move_assumption")
def handle_move_assumption(ack, body, client, logger):  # noqa: ANN001
    ack()
    try:
        assumption_id = body["actions"][0]["value"]
        options = [
            {"text": {"type": "plain_text", "text": "Now"}, "value": "Now"},
            {"text": {"type": "plain_text", "text": "Next"}, "value": "Next"},
            {"text": {"type": "plain_text", "text": "Later"}, "value": "Later"},
        ]
        client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "callback_id": "move_assumption_submit",
                "private_metadata": assumption_id,
                "title": {"type": "plain_text", "text": "Move Assumption"},
                "submit": {"type": "plain_text", "text": "Move"},
                "close": {"type": "plain_text", "text": "Cancel"},
                "blocks": [
                    {
                        "type": "input",
                        "block_id": "lane_block",
                        "label": {"type": "plain_text", "text": "Select lane"},
                        "element": {
                            "type": "static_select",
                            "action_id": "lane",
                            "options": options,
                        },
                    }
                ],
            },
        )
    except (KeyError, ValueError, SlackApiError):
        logger.error("Failed to open move assumption modal", exc_info=True)


@app.view("move_assumption_submit")
def handle_move_assumption_submit(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    assumption_id = body["view"].get("private_metadata")
    if not assumption_id:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Assumption not found.")
        return
    try:
        lane = body["view"]["state"]["values"]["lane_block"]["lane"]["selected_option"]["value"]
        db_service.update_assumption_lane(int(assumption_id), lane)
        db_service.update_assumption_horizon(int(assumption_id), lane.lower())
        client.chat_postEphemeral(channel=user_id, user=user_id, text=f"Moved to {lane}.")
        publish_home_tab_async(client, user_id, "roadmap:roadmap")
    except (KeyError, ValueError, SQLAlchemyError):
        logger.error("Failed to move assumption", exc_info=True)


@app.action("design_assumption_experiment")
def handle_design_assumption_experiment(ack, body, client, logger):  # noqa: ANN001
    ack()
    try:
        assumption_id = body["actions"][0]["value"]
        assumption = db_service.get_assumption(int(assumption_id))
        user_id = body["user"]["id"]
        if not assumption:
            client.chat_postEphemeral(channel=user_id, user=user_id, text="Assumption not found.")
            return
        trigger_id = body.get("trigger_id")
        response = client.views_open(
            trigger_id=trigger_id,
            view=experiment_modal(assumption["title"], "Generating suggestions..."),
        )
        view_id = response["view"]["id"]

        def update_modal() -> None:
            suggestions = ai_service.generate_experiment_suggestions(assumption["title"])
            client.views_update(view_id=view_id, view=experiment_modal(assumption["title"], suggestions))

        run_in_background(update_modal)
    except Exception as exc:  # noqa: BLE001
        logger.error("Design experiment action failed", exc_info=True)


# --- 7. GOOGLE WORKSPACE EXPORTS ---
@app.command("/evidently-export-slides")
def export_slides(ack, body, respond, logger):  # noqa: ANN001
    ack()
    user_id = body.get("user_id")
    try:
        if not google_workspace_service:
            respond("Google Workspace is not configured.")
            return
        project = db_service.get_active_project(user_id)
        if not project:
            respond("Please complete onboarding to create a project first.")
            return
        slides = [
            f"Innovation score: {project.get('innovation_score', 0)}%",
            f"Active assumptions: {len(project.get('assumptions', []))}",
            "Roadmap overview: Now / Next / Later",
        ]
        link = google_workspace_service.create_slide_deck("OCP Dashboard", slides)
        if not link:
            respond("I could not create a slide deck just now.")
            return
        respond(f"I've created a slide deck for your stakeholder meeting: {link}")
    except Exception as exc:  # noqa: BLE001
        logger.error("Error exporting slides", exc_info=True)
        respond("Slide export failed.")


@app.command("/evidently-draft-plan")
def draft_plan(ack, body, respond, logger):  # noqa: ANN001
    ack()
    try:
        if not google_workspace_service:
            respond("Google Workspace is not configured.")
            return
        context = body.get("text", "").strip()
        plan_content = (
            f"# Project Plan\nContext: {context or 'No extra context provided.'}\n\n"
            + "\n\n".join(
                [f"## {stage.title()}\n{desc}" for stage, desc in knowledge_base.FRAMEWORK_STAGES.items()]
            )
        )
        link = google_workspace_service.create_doc("Project Plan", plan_content)
        if not link:
            respond("I couldn't draft the plan right now.")
            return
        respond(f"I've drafted a Test & Learn plan based on our chat: {link}")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to draft plan", exc_info=True)
        respond("Plan drafting failed.")


@app.command("/evidently-nudge")
def handle_nudge_command(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user_id"]
    channel_id = body["channel_id"]
    try:
        project = db_service.get_project_by_channel(channel_id) or db_service.get_active_project(user_id)
        if not project:
            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text="Please select a project first.",
            )
            return
        assumptions = project.get("assumptions", [])
        cutoff = datetime.utcnow() - timedelta(days=14)
        stale = []
        for assumption in assumptions:
            if assumption.get("status") != "Testing":
                continue
            last_tested = assumption.get("last_tested_at")
            if not last_tested:
                continue
            try:
                if datetime.fromisoformat(last_tested) < cutoff:
                    stale.append(assumption)
            except ValueError:
                continue
        count = len(stale)
        text = f"Found {count} stale assumptions. View the board in the Home tab."
        client.chat_postEphemeral(channel=channel_id, user=user_id, text=text)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to run nudge command", exc_info=True)
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="Unable to check stale assumptions right now.",
        )


def daily_standup_job(client):  # noqa: ANN001
    """Iterate active projects and ask for daily updates."""
    today = date.today()
    if today.weekday() >= 5 or today.isoformat() in PUBLIC_HOLIDAYS:
        return
    projects = db_service.get_active_projects()
    for project in projects:
        channel_id = project.get("channel_id")
        if not channel_id:
            continue
        client.chat_postMessage(
            channel=channel_id,
            text="☀️ Daily Check-in!",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"Morning team! What's the main focus for *{project['name']}* today?"
                        ),
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Running Experiment"},
                            "action_id": "update_status_running",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Analyzing Data"},
                            "action_id": "update_status_analysis",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Blocked 🛑"},
                            "action_id": "update_status_blocked",
                        },
                    ],
                },
            ],
        )



@app.action("update_status_running")
def handle_status_running(ack, body, client):  # noqa: ANN001
    ack()
    client.chat_postMessage(
        channel=body["channel"]["id"],
        text=f"🧪 <@{body['user']['id']}> is running an experiment today.",
    )


@app.action("update_status_analysis")
def handle_status_analysis(ack, body, client):  # noqa: ANN001
    ack()
    client.chat_postMessage(
        channel=body["channel"]["id"],
        text=f"📊 <@{body['user']['id']}> is analyzing data today.",
    )


@app.action("update_status_blocked")
def handle_status_blocked(ack, body, client):  # noqa: ANN001
    ack()
    client.chat_postMessage(
        channel=body["channel"]["id"],
        text=f"🛑 <@{body['user']['id']}> is blocked and needs help.",
    )


def weekly_backup_job(client):  # noqa: ANN001
    if not Config.BACKUP_CHANNEL:
        return
    output_path = backup_service.dump_database(Path("backups"))
    if not output_path:
        return
    messenger_service.upload_file(
        channel=Config.BACKUP_CHANNEL,
        file=output_path,
        filename=output_path.name,
        title="Evidently Weekly Backup",
        comment="Weekly database backup.",
    )


if Config.STANDUP_ENABLED:
    standup_scheduler = BackgroundScheduler()
    standup_scheduler.add_job(
        daily_standup_job,
        "cron",
        hour=Config.STANDUP_HOUR,
        minute=Config.STANDUP_MINUTE,
        day_of_week="mon-fri",
        args=[app.client],
    )
    standup_scheduler.start()

if Config.BACKUP_ENABLED:
    backup_scheduler = BackgroundScheduler()
    backup_scheduler.add_job(
        weekly_backup_job,
        "cron",
        day_of_week="sun",
        hour=2,
        minute=0,
        args=[app.client],
    )
    backup_scheduler.start()

daily_dashboard_scheduler = start_scheduler(
    app.client,
    db_service,
    lambda user_id, project, all_projects: get_home_view(
        user_id,
        project,
        all_projects,
        playbook_service=playbook,
    ),
)
