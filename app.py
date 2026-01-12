import io
import logging
import re
import threading
import time
from aiohttp import web
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from blocks.ui_manager import UIManager
from blocks.interactions import (
    case_study_modal,
    error_block,
    get_ai_summary_block,
    get_loading_block,
)
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
from services import knowledge_base
from services.ai_service import EvidenceAI
from services.db_service import DbService
from services.decision_service import DecisionRoomService
from services.google_workspace_service import GoogleWorkspaceService
from services.integration_service import IntegrationService
from services.playbook_service import PlaybookService
from services.toolkit_service import ToolkitService


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = App(token=Config.SLACK_BOT_TOKEN, signing_secret=Config.SLACK_SIGNING_SECRET)
ai_service = EvidenceAI()
db_service = DbService()
decision_service = DecisionRoomService(db_service)
playbook = PlaybookService()
integration_service = IntegrationService()
toolkit_service = ToolkitService()
try:
    google_workspace_service = GoogleWorkspaceService()
except Exception:  # noqa: BLE001
    logging.warning("Google Workspace credentials missing; exports disabled.")
    google_workspace_service = None


CHANNEL_TAB_TEMPLATES = {
    "experiments": {"title": "Experiments", "emoji": "🧪"},
    "manual": {"title": "Manual", "emoji": "📘"},
    "decisions": {"title": "Decisions", "emoji": "🗳️"},
}


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
        publish_home_tab(client, user_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("Error publishing home tab: %s", exc, exc_info=True)


def publish_home_tab(client, user_id: str, active_tab: str = "overview") -> None:
    project_data = db_service.get_active_project(user_id)
    metrics = None
    stage_info = None
    next_best_actions = None
    all_projects = None
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
    )
    client.views_publish(user_id=user_id, view=view)


@app.action("refresh_home")
def refresh_home(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    publish_home_tab(client, user_id)


@app.action(re.compile(r"^(nav|tab)_"))
def handle_navigation(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    tab = body["actions"][0]["value"]
    publish_home_tab(client, user_id, tab)


@app.action("setup_step_1")
def start_setup(ack, body, client):  # noqa: ANN001
    ack()
    client.views_open(trigger_id=body["trigger_id"], view=get_setup_step_1_modal())


@app.action("create_collection_modal")
def open_collection_modal(ack, body, client):  # noqa: ANN001
    ack()
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "create_collection_submit",
            "title": {"type": "plain_text", "text": "New Collection"},
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
        publish_home_tab(client, user_id, "roadmap:collections")
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
        publish_home_tab(client, user_id, "team:automation")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to create automation rule: %s", exc, exc_info=True)


@app.action("select_active_project")
def handle_project_switch(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    selected_project_id = body["actions"][0]["selected_option"]["value"]
    db_service.set_active_project(user_id, int(selected_project_id))
    publish_home_tab(client, user_id)


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
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "📘 Evidently Instruction Manual"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "*Welcome to your AI Innovation Assistant.*"}},
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*1. Setup & Projects*\n"
                    "Type `/evidently-status` to see your current project health. "
                    "Go to the Home Tab to switch projects."
                ),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*2. The Toolkit*\nType `/evidently-methods [stage]` (e.g., 'discovery') to get method cards.",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*3. Rapid Interviewing*\nType `/evidently-ask [method]` (e.g., 'User Interview') to get a script of questions instantly.",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*4. Analysis*\nReply to any thread with `@Evidently` to extract insights.",
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
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"🚀 Project Status: {project['name']}"}},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Current Stage:*\n{project['stage']}"},
                {"type": "mrkdwn", "text": f"*Innovation Score:*\n{project.get('innovation_score', 0)}/100"},
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

    client.chat_postMessage(
        channel=body["channel_id"],
        blocks=blocks,
        text=f"Project Status: {project['name']}",
    )


@app.command("/evidently-ask")
def handle_ask_command(ack, body, client):  # noqa: ANN001
    """
    Instantly fetches interview questions for a specific method.
    Usage: /evidently-ask User Interview
    """
    ack()
    user_id = body["user_id"]
    text = body.get("text", "").strip()
    method_name = text if text else "User Interview"

    questions = toolkit_service.get_question_bank(method_name)
    formatted_questions = "\n".join([f"• {question}" for question in questions])
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"📋 *Script: {method_name} Questions*"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": formatted_questions}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": "Copy these into your notes or read them aloud."}]},
    ]
    client.chat_postEphemeral(
        channel=body["channel_id"],
        user=user_id,
        blocks=blocks,
        text=f"{method_name} questions",
    )


@app.view("setup_final_submit")
def handle_final_setup(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    try:
        data = body["view"]["state"]["values"]
        problem = body["view"]["private_metadata"]
        name = data["name_block"]["name_input"]["value"]
        stage = data["stage_block"]["stage_input"]["selected_option"]["value"]

        db_service.create_project(user_id, name, description=problem, stage=stage)

        client.chat_postMessage(
            channel=user_id,
            blocks=[
                NestaUI.header(f"🎉 {name} is live!"),
                NestaUI.section(
                    f"We've set your stage to *{stage}*.\nAdd your first assumption to start de-risking."
                ),
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "+ Add Assumption"},
                            "action_id": "open_create_assumption",
                        }
                    ],
                },
            ],
            text="Project created",
        )
        publish_home_tab(client, user_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to complete setup: %s", exc, exc_info=True)


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
                            {"text": {"type": "plain_text", "text": "User Interview"}, "value": "User Interview"},
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
    method = values["method_block"]["method_select"]["selected_option"]["value"]
    channel_id = values["channel_select"]["channel_input"]["selected_channel"]
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
    publish_home_tab(client, user_id, "discovery:canvas")


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
    suggestion = ai_service.generate_canvas_suggestion(section, context)
    db_service.add_canvas_item(project["id"], section, suggestion, is_ai=True)
    publish_home_tab(client, user_id, "discovery:canvas")


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
    publish_home_tab(client, user_id, "experiments:framework")


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
    publish_home_tab(client, user_id, "team:decision")


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
        publish_home_tab(client, user_id, "team:integrations")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to link channel: %s", exc, exc_info=True)
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Unable to link that channel right now.")


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
        publish_home_tab(client, user_id, "team:integrations")
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
    if not folder:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Google Drive is not configured.")
        return
    db_service.add_integration_link(project["id"], "drive", folder["id"])
    client.chat_postEphemeral(
        channel=user_id,
        user=user_id,
        text=f"Drive folder created: {folder['link']}",
    )
    publish_home_tab(client, user_id, "team:integrations")


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
    if not asana_project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Asana is not configured.")
        return
    db_service.add_integration_link(project["id"], "asana", asana_project["id"])
    client.chat_postEphemeral(
        channel=user_id,
        user=user_id,
        text=f"Asana project created: {asana_project['link']}",
    )
    publish_home_tab(client, user_id, "team:integrations")


@app.action("export_report")
def handle_export_report(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    project = db_service.get_active_project(user_id)
    if not project:
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
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
    dm_channel = client.conversations_open(users=user_id)["channel"]["id"]
    client.files_upload_v2(
        channel=dm_channel,
        file=buffer,
        filename=f"{project['name'].lower().replace(' ', '-')}-report.pdf",
        title="Evidently Learning Report",
        initial_comment="Here is your generated executive report. 📄",
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

        db_service.create_assumption(
            project_id=project["id"],
            data={
                "title": title,
                "lane": lane,
                "validation_status": status,
                "evidence_density": density,
            },
        )
        publish_home_tab(client, user_id, "roadmap:roadmap")
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
        publish_home_tab(client, user_id, "roadmap:roadmap")
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
    client.views_open(
        trigger_id=body["trigger_id"],
        view={"type": "modal", "title": {"type": "plain_text", "text": "AI Suggestions"}, "blocks": blocks},
    )


@app.action("create_experiment_manual")
def open_manual_experiment_modal(ack, body, client):  # noqa: ANN001
    ack()
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "create_experiment_submit",
            "title": {"type": "plain_text", "text": "New Experiment"},
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
                            {"text": {"type": "plain_text", "text": "User Interview"}, "value": "User Interview"},
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
        publish_home_tab(client, user_id, "experiments:active")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to create experiment: %s", exc, exc_info=True)


@app.action("update_experiment")
def open_update_experiment_modal(ack, body, client):  # noqa: ANN001
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

    status_options = [
        {"text": {"type": "plain_text", "text": "Planning"}, "value": "Planning"},
        {"text": {"type": "plain_text", "text": "🟢 Live"}, "value": "Live"},
        {"text": {"type": "plain_text", "text": "✅ Completed"}, "value": "Completed"},
        {"text": {"type": "plain_text", "text": "🛑 Paused"}, "value": "Paused"},
    ]
    status_option = next(
        (option for option in status_options if option["value"] == experiment.get("status")),
        None,
    )

    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "update_experiment_submit",
            "private_metadata": str(experiment_id),
            "title": {"type": "plain_text", "text": "Update Status"},
            "blocks": [
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


@app.view("update_experiment_submit")
def handle_update_experiment_submit(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    experiment_id = int(body["view"]["private_metadata"])
    try:
        values = body["view"]["state"]["values"]
        status = values["status_block"]["status"]["selected_option"]["value"]
        kpi_value = values.get("kpi_block", {}).get("kpi_value", {}).get("value")

        db_service.update_experiment(experiment_id, status=status, kpi=kpi_value)
        project = db_service.get_active_project(user_id)
        if project and project.get("channel_id"):
            status_emoji = {"Live": "🟢", "Completed": "✅", "Paused": "🛑"}.get(status, "🔵")
            client.chat_postMessage(
                channel=project["channel_id"],
                text=f"{status_emoji} *Experiment Update: {status}*",
            )
        publish_home_tab(client, user_id, "experiments:active")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to update experiment: %s", exc, exc_info=True)


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
                            "text": "👋 *Thanks for adding me!* I'm Evidently, your AI innovation assistant.",
                        },
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                "Here is how you can use me in this channel:\n\n"
                                "🧵 *Analyse Threads:* Reply to any thread and mention `@Evidently` to extract "
                                "hypotheses and evidence.\n"
                                "⚡ *Shortcuts:* Click the `...` on any message → `Apps` → `Extract Insights`.\n"
                                "🛠 *Toolkit:* Type `/evidently-methods` to get rapid suggestions for your current stage."
                            ),
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
        suggestions = ai_service.generate_experiment_suggestions(assumption_text)
        client.views_open(trigger_id=trigger_id, view=experiment_modal(assumption_text, suggestions))
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
        narrative = ai_service.recommend_methods(stage, "")
        blocks = method_cards(stage)
        respond(text=narrative, blocks=blocks)
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
        elif action == "exp":
            assumption = db_service.get_assumption(int(assumption_id))
            if not assumption:
                client.chat_postEphemeral(channel=user_id, user=user_id, text="Assumption not found.")
                return
            trigger_id = body.get("trigger_id")
            suggestions = ai_service.generate_experiment_suggestions(assumption["title"])
            client.views_open(trigger_id=trigger_id, view=experiment_modal(assumption["title"], suggestions))
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


# --- 8. START ---
if __name__ == "__main__":
    def run_health_server() -> None:
        health_app = web.Application()

        async def health_check(request: web.Request) -> web.Response:
            return web.json_response({"status": "ok"})

        health_app.router.add_get("/", health_check)
        health_app.router.add_get("/healthz", health_check)
        web.run_app(health_app, host=Config.HOST, port=Config.PORT, print=None, handle_signals=False)

    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()

    handler = SocketModeHandler(app, Config.SLACK_APP_TOKEN)
    handler.start()
