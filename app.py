import logging
import re
import threading

from aiohttp import web
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from blocks.home_tab import get_home_view
from blocks.interactions import (
    case_study_modal,
    error_block,
    get_ai_summary_block,
    get_decision_room_blocks,
    get_loading_block,
    get_nudge_block,
)
from blocks.modals import experiment_modal
from blocks.methods_ui import method_cards
from config import Config
from services import knowledge_base
from services.ai_service import EvidenceAI
from services.db_service import ProjectDB
from services.chart_service import ChartService
from services.decision_service import DecisionRoom
from services.drive_service import DriveService
from services.google_workspace_service import GoogleWorkspaceService


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = App(token=Config.SLACK_BOT_TOKEN, signing_secret=Config.SLACK_SIGNING_SECRET)
ai_service = EvidenceAI()
db_service = ProjectDB()
decision_service = DecisionRoom()

drive_service = DriveService()
try:
    google_workspace_service = GoogleWorkspaceService()
except Exception:  # noqa: BLE001
    logging.warning("Google Workspace credentials missing; exports disabled.")
    google_workspace_service = None


# --- 1. HOME TAB (OCP Dashboard) ---
@app.event("app_home_opened")
def update_home_tab(client, event, logger):  # noqa: ANN001
    try:
        user_id = event["user"]
        project_data = db_service.get_user_project(user_id)
        current_workspace = db_service.get_current_view(user_id)
        home_view = get_home_view(user_id, project_data, current_workspace)
        client.views_publish(user_id=user_id, view=home_view)
    except Exception as exc:  # noqa: BLE001
        logger.error("Error publishing home tab: %s", exc, exc_info=True)


@app.action(re.compile(r"^navigate_workspace_.*"))
def handle_navigation(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    workspace = body["actions"][0]["value"]
    try:
        db_service.set_current_view(user_id, workspace)
        project_data = db_service.get_user_project(user_id)
        view = get_home_view(user_id, project_data, workspace)
        client.views_publish(user_id=user_id, view=view)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to handle navigation: %s", exc, exc_info=True)


# --- 2. 'SO WHAT?' AI SUMMARISER WITH LIVE STATUS ---
@app.event("app_mention")
def handle_mention(body, say, client, logger):  # noqa: ANN001
    event = body["event"]
    thread_ts = event.get("thread_ts", event["ts"])
    channel_id = event["channel"]

    loading_msg = say(blocks=get_loading_block("Analysing thread context..."), thread_ts=thread_ts)

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
    except Exception as exc:
        logger.error("Error handling mention: %s", exc, exc_info=True)
        client.chat_update(
            channel=channel_id,
            ts=loading_msg["ts"],
            text=f":warning: I crashed while thinking: {str(exc)}",
        )

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
            db_service.update_assumption_status(assumption_id, "active")
            client.chat_postEphemeral(
                channel=body["channel_id"], user=user_id, text=f"Assumption {assumption_id} marked as validated."
            )
        elif action_type == "arch":
            db_service.update_assumption_status(assumption_id, "archived")
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
        db_service.update_assumption_status(assumption_id, "active")
        client.chat_postMessage(channel=user_id, text=f"✅ Assumption {assumption_id} marked as active.")
    except Exception as exc:  # noqa: BLE001
        logger.error("Error in handle_keep action: %s", exc, exc_info=True)


@app.action("archive_assumption")
def handle_archive(ack, body, client, logger):  # noqa: ANN001
    ack()
    try:
        user_id = body["user"]["id"]
        assumption_id = body["actions"][0]["value"]
        db_service.update_assumption_status(assumption_id, "archived")
        client.chat_postMessage(channel=user_id, text=f"🗑️ Assumption {assumption_id} archived.")
    except Exception as exc:  # noqa: BLE001
        logger.error("Error in handle_archive action: %s", exc, exc_info=True)


# --- 4. GOOGLE DRIVE SYNC ---
@app.command("/evidently-link-doc")
def link_google_doc(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user_id"]
    doc_url = body.get("text", "").strip()
    try:
        file_id = drive_service.extract_id_from_url(doc_url)
        if not file_id:
            client.chat_postEphemeral(channel=user_id, user=user_id, text="Please provide a valid Google Doc URL or ID.")
            return

        db_service.link_drive_file(user_id, file_id)
        client.chat_postEphemeral(channel=user_id, user=user_id, text="🔗 Linked document. Starting first sync...")

        content = drive_service.get_file_content(file_id)
        if not content:
            client.chat_postEphemeral(channel=user_id, user=user_id, text="I couldn't read that document. Check sharing settings.")
            return

        analysis = ai_service.analyze_thread_structured(content)
        if analysis.get("error"):
            client.chat_postEphemeral(channel=user_id, user=user_id, text="AI could not parse the document.")
            return

        db_service.save_assumptions(user_id, analysis.get("assumptions", []))
        client.chat_postEphemeral(
            channel=user_id,
            user=user_id,
            text=f"✅ Synced {len(analysis.get('assumptions', []))} assumptions from the document.",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Error linking Google Doc: %s", exc, exc_info=True)
        client.chat_postEphemeral(channel=user_id, user=user_id, text="Sync failed. Please try again later.")


@app.action("trigger_evidence_sync")
def handle_sync(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    try:
        project = db_service.get_user_project(user_id)
        file_id = project.get("drive_file_id")
        if not file_id:
            client.chat_postMessage(channel=user_id, text="Link a document first with /evidently-link-doc.")
            return

        client.chat_postMessage(channel=user_id, text="🔄 Syncing with Google Drive... reading your assumption log.")
        doc_text = drive_service.get_file_content(file_id)
        if not doc_text:
            client.chat_postMessage(channel=user_id, text="⚠️ I couldn't access the file. Did you share it with me?")
            return

        analysis = ai_service.analyze_thread_structured(doc_text)
        if analysis.get("error"):
            client.chat_postMessage(channel=user_id, text="❌ Sync failed while parsing the document.")
            return

        db_service.save_assumptions(user_id, analysis.get("assumptions", []))
        client.chat_postMessage(
            channel=user_id,
            text=f"✅ Sync complete. Found {len(analysis.get('assumptions', []))} assumptions.",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Error in handle_sync action: %s", exc, exc_info=True)
        client.chat_postMessage(channel=user_id, text="❌ Sync Failed: An unexpected error occurred.")


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
@app.action("start_decision_session")
def start_decision_room(ack, body, client, logger):  # noqa: ANN001
    ack()
    try:
        channel_id = body.get("channel", {}).get("id") or body.get("channel_id")
        if not channel_id:
            return

        session_id = decision_service.create_session(channel_id, "Prioritise Assumptions")
        client.chat_postMessage(
            channel=channel_id,
            blocks=get_decision_room_blocks(session_id, "waiting"),
            text="Decision Room Opened",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Error opening decision room: %s", exc, exc_info=True)


@app.action("reveal_decision_votes")
def reveal_decision_votes(ack, body, client, logger):  # noqa: ANN001
    ack()
    try:
        session_id = body["actions"][0]["value"]
        channel_id = body.get("channel", {}).get("id") or body.get("channel_id")
        votes = decision_service.get_votes(session_id)
        results = decision_service.reveal_votes(session_id)
        if not results:
            client.chat_postEphemeral(channel=channel_id, user=body["user"]["id"], text="Session not found.")
            return

        results["heatmap_url"] = ChartService.generate_decision_heatmap(votes)
        client.chat_postMessage(
            channel=channel_id,
            blocks=get_decision_room_blocks(session_id, "revealed", results),
            text="Votes revealed",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Error revealing votes: %s", exc, exc_info=True)


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


@app.command("/evidently-vote")
def cast_vote(ack, body, respond, logger):  # noqa: ANN001
    ack()
    user_id = body.get("user_id")
    channel_id = body.get("channel_id")
    text = (body.get("text") or "").strip()
    parts = text.split()
    if len(parts) < 2:
        respond("Please provide impact and uncertainty scores, e.g. `/evidently-vote 4 2`.")
        return

    try:
        impact, uncertainty = int(parts[0]), int(parts[1])
        session_id = decision_service.get_active_session(channel_id)
        if not session_id:
            respond("No open Decision Room found in this channel. Start one from the Team tab.")
            return
        decision_service.cast_vote(session_id, user_id, impact, uncertainty)
        respond(f"Vote recorded: impact {impact}, uncertainty {uncertainty}. Your vote stays hidden until reveal.")
    except ValueError:
        respond("Scores must be numbers, e.g. `/evidently-vote 5 3`.")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to record vote", exc_info=True)
        respond("Could not record your vote just now.")


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
        action, assumption_id = action_value.split("::", 1)
        user_id = body["user"]["id"]
        message = {
            "roadmap": "Added to roadmap backlog.",
            "experiment": "I'll help you design an experiment soon.",
            "archive": "Assumption archived from the canvas.",
        }.get(action, "Action received.")
        client.chat_postEphemeral(channel=user_id, user=user_id, text=message)
        if action == "archive":
            db_service.update_assumption_status(assumption_id, "archived")
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
        project = db_service.get_user_project(user_id)
        slides = [
            f"Opportunity confidence: {project.get('progress_score', 0)}%",
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
        web.run_app(health_app, host="0.0.0.0", port=Config.PORT, print=None)

    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()

    handler = SocketModeHandler(app, Config.SLACK_APP_TOKEN)
    handler.start()
