import logging
import threading
import time

from aiohttp import web
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from blocks.home_tab import get_home_view
from blocks.interactions import (
    case_study_modal,
    error_block,
    get_ai_summary_block,
    get_loading_block,
)
from blocks.nesta_ui import NestaUI
from blocks.onboarding import get_onboarding_welcome, get_setup_step_1_modal, get_setup_step_2_modal
from blocks.modals import experiment_modal
from blocks.methods_ui import method_cards
from config import Config
from services import knowledge_base
from services.ai_service import EvidenceAI
from services.db_service import DbService
from services.decision_service import DecisionRoomService
from services.google_workspace_service import GoogleWorkspaceService
from services.playbook_service import PlaybookService


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = App(token=Config.SLACK_BOT_TOKEN, signing_secret=Config.SLACK_SIGNING_SECRET)
ai_service = EvidenceAI()
db_service = DbService()
decision_service = DecisionRoomService(db_service)
playbook = PlaybookService()
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
        project_data = db_service.get_active_project(user_id)
        if project_data:
            home_view = get_home_view(project_data, playbook.get_random_tip())
        else:
            home_view = get_onboarding_welcome()
        client.views_publish(user_id=user_id, view=home_view)
    except Exception as exc:  # noqa: BLE001
        logger.error("Error publishing home tab: %s", exc, exc_info=True)


def publish_home_tab(client, user_id: str) -> None:
    project_data = db_service.get_active_project(user_id)
    view = get_home_view(project_data, playbook.get_random_tip()) if project_data else get_onboarding_welcome()
    client.views_publish(user_id=user_id, view=view)


@app.action("refresh_home")
def refresh_home(ack, body, client):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    publish_home_tab(client, user_id)


@app.action("setup_step_1")
def start_setup(ack, body, client):  # noqa: ANN001
    ack()
    client.views_open(trigger_id=body["trigger_id"], view=get_setup_step_1_modal())


@app.view("setup_step_2_submit")
def handle_step_1(ack, body, client):  # noqa: ANN001
    problem = body["view"]["state"]["values"]["problem_block"]["problem_input"]["value"]
    ack(response_action="push", view=get_setup_step_2_modal(problem))


@app.view("setup_final_submit")
def handle_final_setup(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    try:
        data = body["view"]["state"]["values"]
        problem = body["view"]["private_metadata"]
        name = data["name_block"]["name_input"]["value"]
        phase = data["phase_block"]["phase_input"]["selected_option"]["value"]

        db_service.create_project(user_id, name, description=problem, phase=phase)

        client.chat_postMessage(
            channel=user_id,
            blocks=[
                NestaUI.header(f"🎉 {name} is live!"),
                NestaUI.section(
                    f"We've set your phase to *{phase}*.\nAdd your first assumption to start de-risking."
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


@app.action("open_create_assumption")
def open_create_assumption_modal(ack, body, client):  # noqa: ANN001
    ack()
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "create_assumption_submit",
            "title": {"type": "plain_text", "text": "New Assumption"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "assumption_title",
                    "label": {"type": "plain_text", "text": "Assumption"},
                    "element": {"type": "plain_text_input", "action_id": "title_input"},
                },
                {
                    "type": "input",
                    "block_id": "assumption_category",
                    "label": {"type": "plain_text", "text": "Category"},
                    "element": {
                        "type": "static_select",
                        "action_id": "category_input",
                        "options": [
                            {"text": {"type": "plain_text", "text": "Desirability"}, "value": "desirability"},
                            {"text": {"type": "plain_text", "text": "Viability"}, "value": "viability"},
                            {"text": {"type": "plain_text", "text": "Feasibility"}, "value": "feasibility"},
                            {"text": {"type": "plain_text", "text": "Ethics"}, "value": "ethics"},
                        ],
                    },
                },
                {
                    "type": "input",
                    "block_id": "assumption_confidence",
                    "label": {"type": "plain_text", "text": "Confidence Score (0-100)"},
                    "element": {"type": "plain_text_input", "action_id": "confidence_input"},
                },
                {
                    "type": "input",
                    "block_id": "assumption_evidence",
                    "label": {"type": "plain_text", "text": "Evidence Score (0-100)"},
                    "element": {"type": "plain_text_input", "action_id": "evidence_input"},
                },
                {
                    "type": "input",
                    "block_id": "assumption_impact",
                    "label": {"type": "plain_text", "text": "Impact Score (0-100)"},
                    "element": {"type": "plain_text_input", "action_id": "impact_input"},
                },
            ],
            "submit": {"type": "plain_text", "text": "Add"},
        },
    )


@app.view("create_assumption_submit")
def handle_create_assumption(ack, body, client, logger):  # noqa: ANN001
    ack()
    user_id = body["user"]["id"]
    try:
        values = body["view"]["state"]["values"]
        title = values["assumption_title"]["title_input"]["value"]
        category = values["assumption_category"]["category_input"]["selected_option"]["value"]
        confidence_text = values["assumption_confidence"]["confidence_input"]["value"]
        evidence_text = values["assumption_evidence"]["evidence_input"]["value"]
        impact_text = values["assumption_impact"]["impact_input"]["value"]
        scores = {}
        for name, text_value in {
            "confidence": confidence_text,
            "evidence": evidence_text,
            "impact": impact_text,
        }.items():
            try:
                scores[name] = max(0, min(100, int(text_value)))
            except (ValueError, TypeError):
                scores[name] = 0
        confidence, evidence, impact = scores["confidence"], scores["evidence"], scores["impact"]

        project = db_service.get_active_project(user_id)
        if not project:
            client.chat_postEphemeral(channel=user_id, user=user_id, text="Please create a project first.")
            return

        db_service.create_assumption(
            project_id=project["id"],
            data={
                "title": title,
                "category": category,
                "confidence": confidence,
                "evidence": evidence,
                "impact": impact,
                "lane": "backlog",
            },
        )
        home_view = get_home_view(db_service.get_active_project(user_id), playbook.get_random_tip())
        client.views_publish(user_id=user_id, view=home_view)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to create assumption: %s", exc, exc_info=True)


@app.action("design_experiment")
def open_experiment_browser(ack, body, client):  # noqa: ANN001
    ack()
    assumption_id, category = body["actions"][0]["value"].split(":")
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


# --- 2. 'SO WHAT?' AI SUMMARISER WITH LIVE STATUS ---
@app.event("app_mention")
def handle_mention(body, say, client, logger):  # noqa: ANN001
    event = body["event"]
    thread_ts = event.get("thread_ts", event["ts"])
    channel_id = event["channel"]

    loading_msg = say(blocks=get_loading_block("Analysing thread context..."), thread_ts=thread_ts)
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
            db_service.update_assumption_status(int(assumption_id), "active")
            client.chat_postEphemeral(
                channel=body["channel_id"], user=user_id, text=f"Assumption {assumption_id} marked as validated."
            )
        elif action_type == "arch":
            db_service.update_assumption_status(int(assumption_id), "archived")
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
        db_service.update_assumption_status(int(assumption_id), "active")
        client.chat_postMessage(channel=user_id, text=f"✅ Assumption {assumption_id} marked as active.")
    except Exception as exc:  # noqa: BLE001
        logger.error("Error in handle_keep action: %s", exc, exc_info=True)


@app.action("archive_assumption")
def handle_archive(ack, body, client, logger):  # noqa: ANN001
    ack()
    try:
        user_id = body["user"]["id"]
        assumption_id = body["actions"][0]["value"]
        db_service.update_assumption_status(int(assumption_id), "archived")
        client.chat_postMessage(channel=user_id, text=f"🗑️ Assumption {assumption_id} archived.")
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
                    "text": {"type": "mrkdwn", "text": "Pick a channel to host the voting session."},
                },
                {
                    "type": "input",
                    "block_id": "channel_select",
                    "element": {"type": "channels_select", "action_id": "selected_channel"},
                    "label": {"type": "plain_text", "text": "Channel"},
                },
            ],
            "submit": {"type": "plain_text", "text": "Start Voting"},
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


@app.action("vote_keep")
@app.action("vote_kill")
@app.action("vote_pivot")
def handle_voting(ack, body, client):  # noqa: ANN001
    ack()
    decision_service.handle_vote(body, client)


@app.action("end_decision_session")
def end_session(ack, body, client):  # noqa: ANN001
    ack()
    session_id = body["actions"][0]["value"]
    results = db_service.get_session_results(int(session_id))

    text = "*🏁 Voting Session Complete!*\n\n"
    summary_lines = [
        f"• Assumption {assumption_id}: {votes['keep']} Keep, {votes['pivot']} Pivot, {votes['kill']} Kill"
        for assumption_id, votes in results.items()
    ]
    text += "\n".join(summary_lines)

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

        if action in {"backlog", "now", "next", "later"}:
            db_service.update_assumption_lane(int(assumption_id), action)
            client.chat_postEphemeral(channel=user_id, user=user_id, text=f"Moved to {action.title()}.")
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
