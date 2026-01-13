import io
import json
import logging
import re
import threading
import time
from datetime import date
from pathlib import Path
from urllib import error as url_error
from urllib import request as url_request
from aiohttp import web
from apscheduler.schedulers.background import BackgroundScheduler
import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_bolt.workflows.step import WorkflowStep
from slack_sdk.errors import SlackApiError

from blocks.ui_manager import UIManager
from constants import (
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
    error_block,
    get_ai_summary_block,
    get_loading_block,
)
from blocks.modal_factory import ModalFactory
from blocks.nesta_ui import NestaUI
from blocks.onboarding import get_setup_step_1_modal, get_setup_step_2_modal
from blocks.modals import (
    add_canvas_item_modal,
    change_stage_modal,
    create_channel_modal,
    experiment_modal,
    extract_insights_modal,
    get_loading_modal,
    invite_member_modal,
    link_channel_modal,
    silent_scoring_modal,
)
from blocks.methods_ui import method_cards
from config import Config
from config_manager import ConfigManager
from services import knowledge_base
from services.ai_service import EvidenceAI
from services.db_service import DbService
from services.decision_service import DecisionRoomService
from services.backup_service import BackupService
from services.google_workspace_service import GoogleWorkspaceService
from services.integration_service import IntegrationService
from services.ingestion_service import IngestionService
from services.messenger_service import MessengerService
from services.playbook_service import PlaybookService
from services.sync_service import TwoWaySyncService
from services.toolkit_service import ToolkitService


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAX_ASANA_PAYLOAD_ITEM_LENGTH = 100
CHANNEL_PREFIX = "evidently-"

ConfigManager().validate()

app = App(token=Config.SLACK_BOT_TOKEN, signing_secret=Config.SLACK_SIGNING_SECRET)
ai_service = EvidenceAI()
db_service = DbService()
decision_service = DecisionRoomService(db_service)
playbook = PlaybookService()
integration_service = IntegrationService()
toolkit_service = ToolkitService()
ingestion_service = IngestionService()
sync_service = TwoWaySyncService()
messenger_service = MessengerService(app.client)
backup_service = BackupService()
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
@app.event("app_home_opened")
def update_home_tab(client, event, logger):  # noqa: ANN001
    try:
        user_id = event["user"]
        publish_home_tab_async(client, user_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("Error publishing home tab: %s", exc, exc_info=True)


def app_home_opened(client, event, logger):  # noqa: ANN001
    try:
        user_id = event["user"]
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
) -> None:
    project_data = db_service.get_active_project(user_id)
    metrics = None
    stage_info = None
    all_projects = None
    next_best_actions = None
    if project_data:
        metrics = db_service.get_metrics(project_data["id"])
        stage_info = toolkit_service.get_stage_info(project_data["stage"])
        next_best_actions = ai_service.generate_next_best_actions(project_data, metrics)
        all_projects = db_service.get_user_projects(user_id)
    view = UIManager.get_home_view(
        user_id,
        project_data,
        all_projects,
        active_tab,
        metrics,
        stage_info,
        next_best_actions,
        experiment_page,
    )
    client.views_publish(user_id=user_id, view=view)


def publish_home_tab_async(
    client,
    user_id: str,
    active_tab: str = "overview",
    experiment_page: int = 0,
) -> None:
    project_data = db_service.get_active_project(user_id)
    metrics = None
    stage_info = None
    all_projects = None
    if project_data:
        metrics = db_service.get_metrics(project_data["id"])
        stage_info = toolkit_service.get_stage_info(project_data["stage"])
        all_projects = db_service.get_user_projects(user_id)
    view = UIManager.get_home_view(
        user_id,
        project_data,
        all_projects,
        active_tab,
        metrics,
        stage_info,
        next_best_actions=None,
        experiment_page=experiment_page,
    )
    client.views_publish(user_id=user_id, view=view)

    if not project_data:
        return

    def update_actions() -> None:
        try:
            next_best_actions = ai_service.generate_next_best_actions(project_data, metrics)
            refreshed_view = UIManager.get_home_view(
                user_id,
                project_data,
                all_projects,
                active_tab,
                metrics,
                stage_info,
                next_best_actions,
                experiment_page,
            )
            client.views_publish(user_id=user_id, view=refreshed_view)
        except Exception:
            logger.exception("Failed to generate and publish next best actions for user %s", user_id)


@app.action("refresh_home")
def refresh_home(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    publish_home_tab_async(client, user_id)


@app.action(re.compile(r"^(nav|tab)_"))
def handle_navigation(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    tab = body["actions"][0]["value"]
    publish_home_tab_async(client, user_id, tab)


@app.action("setup_step_1")
def start_setup(ack, body, client):  # noqa: ANN001
    ack()
    client.views_open(trigger_id=body["trigger_id"], view=get_setup_step_1_modal())


@app.action("open_create_project_modal")
def open_create_modal(ack, body, client):  # noqa: ANN001
    ack()
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "create_project_submit",
            "title": {"type": "plain_text", "text": "New Project"},
            "blocks": [
                # 1. Project Name Input
                {
                    "type": "input",
                    "block_id": "name_block",
                    "label": {"type": "plain_text", "text": "Project Name"},
                    "element": {"type": "plain_text_input", "action_id": "name"},
                },
                # 2. THE MISSION DROPDOWN (This was likely missing)
                {
                    "type": "input",
                    "block_id": "mission_block",
                    "label": {"type": "plain_text", "text": "Primary Mission"},
                    "element": {
                        "type": "static_select",
                        "action_id": "mission_select",
                        "placeholder": {"type": "plain_text", "text": "Select a mission"},
                        "options": [
                            {"text": {"type": "plain_text", "text": "🟢 A Fairer Start (AFS)"}, "value": "AFS"},
                            {"text": {"type": "plain_text", "text": "🍎 A Healthy Life (AHL)"}, "value": "AHL"},
                            {"text": {"type": "plain_text", "text": "🌱 A Sustainable Future (ASF)"}, "value": "ASF"},
                            {"text": {"type": "plain_text", "text": "🔭 Mission Discovery"}, "value": "Mission Discovery"},
                            {"text": {"type": "plain_text", "text": "🔗 Mission Adjacent"}, "value": "Mission Adjacent"},
                            {"text": {"type": "plain_text", "text": "⚔️ Cross-cutting"}, "value": "Cross-cutting"},
                            {"text": {"type": "plain_text", "text": "📜 Policy"}, "value": "Policy"},
                        ],
                    },
                },
                # 3. Channel Setup
                {
                    "type": "section",
                    "block_id": "channel_block",
                    "text": {"type": "mrkdwn", "text": "*Channel Setup*"},
                    "accessory": {
                        "type": "radio_buttons",
                        "action_id": "channel_action",
                        "options": [
                            {"text": {"type": "plain_text", "text": "Create new channel"}, "value": "create_new"},
                            {"text": {"type": "plain_text", "text": "Use current channel"}, "value": "use_current"},
                        ],
                    },
                },
            ],
            "submit": {"type": "plain_text", "text": "Launch"},
        },
    )


@app.view("create_project_submit")
def handle_create_project(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    values = body["view"]["state"]["values"]

    # 1. Extract Values
    name = values["name_block"]["name"]["value"]

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
    db_service.create_project(user_id, name, "", mission=mission, channel_id=channel_id)

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
    blocks = get_help_manual_blocks()
    client.chat_postEphemeral(
        channel=body["channel_id"],
        user=user_id,
        text="Evidently Help Guide",
        blocks=blocks,
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
            description=problem,
            stage=stage,
            mission=mission,
            channel_id=channel_id,
        )

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
        view={
            "type": "modal",
            "callback_id": "create_assumption_submit",
            "title": {"type": "plain_text", "text": "New Roadmap Item"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "assumption_title",
                    "label": {"type": "plain_text", "text": "Roadmap item"},
                    "element": {"type": "plain_text_input", "action_id": "title_input"},
                },
                {
                    "type": "input",
                    "block_id": "assumption_lane",
                    "label": {"type": "plain_text", "text": "Lane"},
                    "element": {
                        "type": "static_select",
                        "action_id": "lane_input",
                        "options": [
                            {"text": {"type": "plain_text", "text": "Now"}, "value": "Now"},
                            {"text": {"type": "plain_text", "text": "Next"}, "value": "Next"},
                            {"text": {"type": "plain_text", "text": "Later"}, "value": "Later"},
                        ],
                    },
                },
                {
                    "type": "input",
                    "block_id": "assumption_status",
                    "label": {"type": "plain_text", "text": "Validation status"},
                    "element": {
                        "type": "static_select",
                        "action_id": "status_input",
                        "options": [
                            {"text": {"type": "plain_text", "text": "Testing"}, "value": "Testing"},
                            {"text": {"type": "plain_text", "text": "Validated"}, "value": "Validated"},
                            {"text": {"type": "plain_text", "text": "Rejected"}, "value": "Rejected"},
                        ],
                    },
                },
                {
                    "type": "input",
                    "block_id": "assumption_density",
                    "label": {"type": "plain_text", "text": "Evidence density (docs)"},
                    "element": {"type": "plain_text_input", "action_id": "density_input"},
                },
            ],
            "submit": {"type": "plain_text", "text": "Add"},
        },
    )


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


@app.action("open_create_assumption")
@app.action("open_add_assumption")
def open_create_assumption_modal(ack, body, client):  # noqa: ANN001
    ack()
    open_assumption_modal(client, body["trigger_id"])


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
        title = values["assumption_title"]["title_input"]["value"]
        lane = values["assumption_lane"]["lane_input"]["selected_option"]["value"]
        status = values["assumption_status"]["status_input"]["selected_option"]["value"]
        density_text = values["assumption_density"]["density_input"]["value"]
        try:
            density = max(0, int(density_text))
        except (ValueError, TypeError):
            density = 0

        project = db_service.get_active_project(user_id)
        if not project:
            client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
            return

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
                "lane": lane,
                "validation_status": status,
                "evidence_density": density,
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


@app.action("create_experiment_manual")
def open_manual_experiment_modal(ack, body, client):  # noqa: ANN001
    ack()
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
                    "element": {"type": "plain_text_input", "action_id": "hypothesis", "multiline": True},
                },
            ],
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

        project = db_service.get_active_project(user_id)
        if not project:
            client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
            return

        db_service.create_experiment(
            project_id=project["id"],
            title=title,
            method=method,
            hypothesis=hypothesis,
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

    success, message = decision_service.start_session(client, channel_id, user_id)
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
            db_service.update_assumption_lane(int(assumption_id), action)
            client.chat_postEphemeral(channel=user_id, user=user_id, text=f"Moved to {action}.")
        elif action == "delete":
            db_service.delete_assumption(int(assumption_id))
            client.chat_postEphemeral(channel=user_id, user=user_id, text="Assumption deleted.")
            publish_home_tab_async(client, user_id, "roadmap:roadmap")
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
def handle_nudge_command(ack, respond):  # noqa: ANN001
    ack()
    respond("Use the nudges in your home tab to manage assumptions.")


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


def check_stale_assumptions_job(client):  # noqa: ANN001
    stale_assumptions = db_service.get_stale_assumptions()
    for entry in stale_assumptions:
        assumption = entry["assumption"]
        project = entry["project"]
        channel_id = project.get("channel_id")
        if not channel_id:
            owner_id = project.get("created_by")
            if not owner_id:
                continue
            response = client.conversations_open(users=owner_id)
            if not response.get("ok"):
                logger.warning("Unable to open DM for stale assumption alert: %s", response.get("error"))
                continue
            channel_id = response["channel"]["id"]
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*⏰ Stale assumption check-in*\n"
                        f"*Project:* {project['name']}\n"
                        f"*Assumption:* {assumption.get('title', 'Untitled')}\n"
                        f"*Lane:* {assumption.get('lane', 'Now')}\n"
                        f"*Status:* {assumption.get('validation_status', 'Testing')}"
                    ),
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Keep Testing"},
                        "action_id": "keep_testing",
                        "value": str(assumption["id"]),
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Validate"},
                        "action_id": "keep_assumption",
                        "value": str(assumption["id"]),
                        "style": "primary",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Archive"},
                        "action_id": "archive_assumption",
                        "value": str(assumption["id"]),
                        "style": "danger",
                    },
                ],
            },
        ]
        client.chat_postMessage(
            channel=channel_id,
            text=f"Stale assumption reminder for {project['name']}.",
            blocks=blocks,
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

stale_assumption_scheduler = BackgroundScheduler()
stale_assumption_scheduler.add_job(
    check_stale_assumptions_job,
    "interval",
    hours=24,
    args=[app.client],
)
stale_assumption_scheduler.start()


# --- 8. START ---
if __name__ == "__main__":
    def run_health_server() -> None:
        health_app = web.Application()

        async def health_check(request: web.Request) -> web.Response:
            return web.json_response({"status": "ok"})

        health_app.router.add_get("/", health_check)
        health_app.router.add_get("/healthz", health_check)
        health_app.router.add_post("/asana/webhook", handle_asana_webhook)
        web.run_app(health_app, host=Config.HOST, port=Config.PORT, print=None, handle_signals=False)

    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()

    handler = SocketModeHandler(app, Config.SLACK_APP_TOKEN)
    handler.start()
