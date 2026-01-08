import asyncio
import logging

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

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

app = AsyncApp(token=Config.SLACK_BOT_TOKEN, signing_secret=Config.SLACK_SIGNING_SECRET)
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
async def update_home_tab(client, event, logger):  # noqa: ANN001
    try:
        user_id = event["user"]
        project_data = db_service.get_user_project(user_id)
        current_workspace = db_service.get_current_view(user_id)
        home_view = get_home_view(user_id, project_data, current_workspace)
        await client.views_publish(user_id=user_id, view=home_view)
    except Exception as exc:  # noqa: BLE001
        logger.error("Error publishing home tab: %s", exc, exc_info=True)


@app.action("navigate_workspace")
async def handle_navigation(ack, body, client, logger):  # noqa: ANN001
    await ack()
    user_id = body["user"]["id"]
    workspace = body["actions"][0]["value"]
    try:
        db_service.set_current_view(user_id, workspace)
        project_data = db_service.get_user_project(user_id)
        view = get_home_view(user_id, project_data, workspace)
        await client.views_publish(user_id=user_id, view=view)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to handle navigation: %s", exc, exc_info=True)


# --- 2. 'SO WHAT?' AI SUMMARISER WITH LIVE STATUS ---
@app.event("app_mention")
async def handle_mention(body, say, client, logger):  # noqa: ANN001
    event = body["event"]
    thread_ts = event.get("thread_ts", event["ts"])
    channel_id = event["channel"]

    loading_msg = await say(blocks=get_loading_block("Analysing thread context..."), thread_ts=thread_ts)

    stop_animation = asyncio.Event()

    async def animate_loading():
        statuses = [
            "Reading thread history... 📖",
            "Extracting hypotheses... 🧠",
            "Drafting summary... 📝",
        ]
        index = 0
        while not stop_animation.is_set():
            await asyncio.sleep(1.5)
            index = (index + 1) % len(statuses)
            try:
                await client.chat_update(
                    channel=channel_id,
                    ts=loading_msg["ts"],
                    blocks=get_loading_block(statuses[index]),
                )
            except Exception:  # noqa: BLE001
                logger.debug("Unable to update loading animation", exc_info=True)

    animation_task = asyncio.create_task(animate_loading())

    try:
        history = await client.conversations_replies(channel=channel_id, ts=thread_ts)
        messages = history["messages"]
        full_text = "\n".join([f"{m.get('user')}: {m.get('text')}" for m in messages])

        attachments = [
            {"name": file.get("name"), "mimetype": file.get("mimetype")}
            for message in messages
            for file in message.get("files", []) or []
        ]

        # Use run_in_executor for the synchronous AI service call to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        analysis = await loop.run_in_executor(
            None, lambda: ai_service.analyze_thread_structured(full_text, attachments)
        )

        stop_animation.set()
        animation_task.cancel()

        if analysis.get("error"):
            await client.chat_update(
                channel=channel_id,
                ts=loading_msg["ts"],
                blocks=error_block("The AI brain is briefly offline. Please try again."),
                text="Analysis failed",
            )
            return

        await client.chat_update(
            channel=channel_id,
            ts=loading_msg["ts"],
            blocks=get_ai_summary_block(analysis),
            text="Analysis complete",
        )
    except Exception as exc:
        logger.error("Error handling mention: %s", exc, exc_info=True)
        stop_animation.set()
        animation_task.cancel()
        await client.chat_update(
            channel=channel_id,
            ts=loading_msg["ts"],
            text=f":warning: I crashed while thinking: {str(exc)}",
        )

# --- 3. ACTIVE PERSISTENCE / NUDGES ---
@app.action("nudge_action")
async def handle_nudge_action(ack, body, client, logger):  # noqa: ANN001
    await ack()
    user_id = body["user"]["id"]
    action_value = body["actions"][0]["value"]

    try:
        action_type, assumption_id = action_value.split("_", 1)

        if action_type == "gen":
            await client.chat_postEphemeral(
                channel=body["channel_id"],
                user=user_id,
                text=f"Generating experiment for assumption {assumption_id}...",
            )
        elif action_type == "val":
            db_service.update_assumption_status(assumption_id, "active")
            await client.chat_postEphemeral(
                channel=body["channel_id"], user=user_id, text=f"Assumption {assumption_id} marked as validated."
            )
        elif action_type == "arch":
            db_service.update_assumption_status(assumption_id, "archived")
            await client.chat_postEphemeral(
                channel=body["channel_id"], user=user_id, text=f"Assumption {assumption_id} archived."
            )
        else:
            await client.chat_postEphemeral(channel=body["channel_id"], user=user_id, text="Unknown action type.")
    except Exception as exc:  # noqa: BLE001
        logger.error("Error handling nudge action for user %s: %s", user_id, exc, exc_info=True)
        await client.chat_postEphemeral(
            channel=body.get("channel_id"), user=user_id, text="An error occurred while processing your request."
        )


@app.action("keep_assumption")
async def handle_keep(ack, body, client, logger):  # noqa: ANN001
    await ack()
    try:
        user_id = body["user"]["id"]
        assumption_id = body["actions"][0]["value"]
        db_service.update_assumption_status(assumption_id, "active")
        await client.chat_postMessage(channel=user_id, text=f"✅ Assumption {assumption_id} marked as active.")
    except Exception as exc:  # noqa: BLE001
        logger.error("Error in handle_keep action: %s", exc, exc_info=True)


@app.action("archive_assumption")
async def handle_archive(ack, body, client, logger):  # noqa: ANN001
    await ack()
    try:
        user_id = body["user"]["id"]
        assumption_id = body["actions"][0]["value"]
        db_service.update_assumption_status(assumption_id, "archived")
        await client.chat_postMessage(channel=user_id, text=f"🗑️ Assumption {assumption_id} archived.")
    except Exception as exc:  # noqa: BLE001
        logger.error("Error in handle_archive action: %s", exc, exc_info=True)


# --- 4. GOOGLE DRIVE SYNC ---
@app.command("/evidently-link-doc")
async def link_google_doc(ack, body, client, logger):  # noqa: ANN001
    await ack()
    user_id = body["user_id"]
    doc_url = body.get("text", "").strip()
    try:
        file_id = drive_service.extract_id_from_url(doc_url)
        if not file_id:
            await client.chat_postEphemeral(channel=user_id, user=user_id, text="Please provide a valid Google Doc URL or ID.")
            return

        db_service.link_drive_file(user_id, file_id)
        await client.chat_postEphemeral(channel=user_id, user=user_id, text="🔗 Linked document. Starting first sync...")

        content = drive_service.get_file_content(file_id)
        if not content:
            await client.chat_postEphemeral(channel=user_id, user=user_id, text="I couldn't read that document. Check sharing settings.")
            return

        loop = asyncio.get_running_loop()
        content = await loop.run_in_executor(None, drive_service.get_file_content, file_id)
        if analysis.get("error"):
            await client.chat_postEphemeral(channel=user_id, user=user_id, text="AI could not parse the document.")
            return

        db_service.save_assumptions(user_id, analysis.get("assumptions", []))
        await client.chat_postEphemeral(
            channel=user_id,
            user=user_id,
            text=f"✅ Synced {len(analysis.get('assumptions', []))} assumptions from the document.",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Error linking Google Doc: %s", exc, exc_info=True)
        await client.chat_postEphemeral(channel=user_id, user=user_id, text="Sync failed. Please try again later.")


@app.action("trigger_evidence_sync")
async def handle_sync(ack, body, client, logger):  # noqa: ANN001
    await ack()
    user_id = body["user"]["id"]
    try:
        project = db_service.get_user_project(user_id)
        file_id = project.get("drive_file_id")
        if not file_id:
            await client.chat_postMessage(channel=user_id, text="Link a document first with /evidently-link-doc.")
            return

        await client.chat_postMessage(channel=user_id, text="🔄 Syncing with Google Drive... reading your assumption log.")
        doc_text = drive_service.get_file_content(file_id)
        if not doc_text:
            await client.chat_postMessage(channel=user_id, text="⚠️ I couldn't access the file. Did you share it with me?")
            return

        analysis = ai_service.analyze_thread_structured(doc_text)
        if analysis.get("error"):
            await client.chat_postMessage(channel=user_id, text="❌ Sync failed while parsing the document.")
            return

        db_service.save_assumptions(user_id, analysis.get("assumptions", []))
        await client.chat_postMessage(
            channel=user_id,
            text=f"✅ Sync complete. Found {len(analysis.get('assumptions', []))} assumptions.",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Error in handle_sync action: %s", exc, exc_info=True)
        await client.chat_postMessage(channel=user_id, text="❌ Sync Failed: An unexpected error occurred.")


@app.action("gen_experiment_modal")
async def handle_gen_experiment(ack, body, client, logger):  # noqa: ANN001
    await ack()
    try:
        assumption_text = body["actions"][0]["value"]
        trigger_id = body["trigger_id"]
        suggestions = ai_service.generate_experiment_suggestions(assumption_text)
        await client.views_open(trigger_id=trigger_id, view=experiment_modal(assumption_text, suggestions))
    except Exception as exc:  # noqa: BLE001
        logger.error("Error in handle_gen_experiment action: %s", exc, exc_info=True)


# --- 5. DECISION ROOM ---
@app.action("start_decision_session")
async def start_decision_room(ack, body, client, logger):  # noqa: ANN001
    await ack()
    try:
        channel_id = body.get("channel", {}).get("id") or body.get("channel_id")
        if not channel_id:
            return

        session_id = decision_service.create_session(channel_id, "Prioritise Assumptions")
        await client.chat_postMessage(
            channel=channel_id,
            blocks=get_decision_room_blocks(session_id, "waiting"),
            text="Decision Room Opened",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Error opening decision room: %s", exc, exc_info=True)


@app.action("reveal_decision_votes")
async def reveal_decision_votes(ack, body, client, logger):  # noqa: ANN001
    await ack()
    try:
        session_id = body["actions"][0]["value"]
        channel_id = body.get("channel", {}).get("id") or body.get("channel_id")
        votes = decision_service.get_votes(session_id)
        results = decision_service.reveal_votes(session_id)
        if not results:
            await client.chat_postEphemeral(channel=channel_id, user=body["user"]["id"], text="Session not found.")
            return

        results["heatmap_url"] = ChartService.generate_decision_heatmap(votes)
        await client.chat_postMessage(
            channel=channel_id,
            blocks=get_decision_room_blocks(session_id, "revealed", results),
            text="Votes revealed",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Error revealing votes: %s", exc, exc_info=True)


# --- 6. METHODS AND CASE STUDIES ---
@app.command("/evidently-methods")
async def handle_methods(ack, body, respond, logger):  # noqa: ANN001
    await ack()
    stage = (body.get("text") or "").strip().lower() or "define"
    try:
        narrative = ai_service.recommend_methods(stage, "")
        blocks = method_cards(stage)
        await respond(text=narrative, blocks=blocks)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to handle methods command", exc_info=True)
        await respond("Unable to share methods right now.")


@app.command("/evidently-vote")
async def cast_vote(ack, body, respond, logger):  # noqa: ANN001
    await ack()
    user_id = body.get("user_id")
    channel_id = body.get("channel_id")
    text = (body.get("text") or "").strip()
    parts = text.split()
    if len(parts) < 2:
        await respond("Please provide impact and uncertainty scores, e.g. `/evidently-vote 4 2`.")
        return

    try:
        impact, uncertainty = int(parts[0]), int(parts[1])
        session_id = decision_service.get_active_session(channel_id)
        if not session_id:
            await respond("No open Decision Room found in this channel. Start one from the Team tab.")
            return
        decision_service.cast_vote(session_id, user_id, impact, uncertainty)
        await respond(f"Vote recorded: impact {impact}, uncertainty {uncertainty}. Your vote stays hidden until reveal.")
    except ValueError:
        await respond("Scores must be numbers, e.g. `/evidently-vote 5 3`.")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to record vote", exc_info=True)
        await respond("Could not record your vote just now.")


@app.action("view_case_study")
async def open_case_study(ack, body, client, logger):  # noqa: ANN001
    await ack()
    try:
        method = body["actions"][0]["value"]
        trigger_id = body.get("trigger_id")
        await client.views_open(trigger_id=trigger_id, view=case_study_modal(method))
    except Exception as exc:  # noqa: BLE001
        logger.error("Error opening case study modal", exc_info=True)


@app.action("assumption_overflow")
async def handle_assumption_overflow(ack, body, client, logger):  # noqa: ANN001
    await ack()
    try:
        action_value = body["actions"][0]["selected_option"]["value"]
        action, assumption_id = action_value.split("::", 1)
        user_id = body["user"]["id"]
        message = {
            "roadmap": "Added to roadmap backlog.",
            "experiment": "I'll help you design an experiment soon.",
            "archive": "Assumption archived from the canvas.",
        }.get(action, "Action received.")
        await client.chat_postEphemeral(channel=user_id, user=user_id, text=message)
        if action == "archive":
            db_service.update_assumption_status(assumption_id, "archived")
    except Exception as exc:  # noqa: BLE001
        logger.error("Overflow action failed", exc_info=True)


# --- 7. GOOGLE WORKSPACE EXPORTS ---
@app.command("/evidently-export-slides")
async def export_slides(ack, body, respond, logger):  # noqa: ANN001
    await ack()
    user_id = body.get("user_id")
    try:
        if not google_workspace_service:
            await respond("Google Workspace is not configured.")
            return
        project = db_service.get_user_project(user_id)
        slides = [
            f"Opportunity confidence: {project.get('progress_score', 0)}%",
            f"Active assumptions: {len(project.get('assumptions', []))}",
            "Roadmap overview: Now / Next / Later",
        ]
        link = google_workspace_service.create_slide_deck("OCP Dashboard", slides)
        if not link:
            await respond("I could not create a slide deck just now.")
            return
        await respond(f"I've created a slide deck for your stakeholder meeting: {link}")
    except Exception as exc:  # noqa: BLE001
        logger.error("Error exporting slides", exc_info=True)
        await respond("Slide export failed.")


@app.command("/evidently-draft-plan")
async def draft_plan(ack, body, respond, logger):  # noqa: ANN001
    await ack()
    try:
        if not google_workspace_service:
            await respond("Google Workspace is not configured.")
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
            await respond("I couldn't draft the plan right now.")
            return
        await respond(f"I've drafted a Test & Learn plan based on our chat: {link}")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to draft plan", exc_info=True)
        await respond("Plan drafting failed.")


# --- 8. START ---
if __name__ == "__main__":
    handler = AsyncSocketModeHandler(app, Config.SLACK_APP_TOKEN)
    asyncio.run(handler.start_async())
