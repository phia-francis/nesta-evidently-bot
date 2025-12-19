import logging
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from config import Config

# Services
from services.ai_service import EvidenceAI
from services.db_service import ProjectDB
from blocks.home_tab import get_home_view
from blocks.interactions import get_nudge_block, get_ai_summary_block

# Init
logging.basicConfig(level=logging.INFO)
app = App(token=Config.SLACK_BOT_TOKEN, signing_secret=Config.SLACK_SIGNING_SECRET)
ai_service = EvidenceAI()
db_service = ProjectDB()

# --- 1. HOME TAB (OCP Dashboard) ---
@app.event("app_home_opened")
def update_home_tab(client, event, logger):
    try:
        user_id = event["user"]
        # Fetch project state
        project_data = db_service.get_user_project(user_id)
        
        # Build View
        home_view = get_home_view(user_id, project_data)
        
        client.views_publish(user_id=user_id, view=home_view)
    except Exception as e:
        logger.error(f"Error publishing home tab: {e}")

# --- 2. 'SO WHAT?' AI SUMMARISER ---
@app.event("app_mention")
def handle_mention(body, say, client, logger):
    """
    Listens for @Evidently mentions.
    Fetches thread history and uses Gemini to summarize and extract OCP assumptions.
    """
    event = body["event"]
    thread_ts = event.get("thread_ts", event["ts"])
    channel_id = event["channel"]

    # Reaction to indicate processing
    client.reactions_add(channel=channel_id, name="eyes", timestamp=event["ts"])

    # Fetch History
    try:
        history = client.conversations_replies(channel=channel_id, ts=thread_ts)
        messages = history['messages']
        full_text = "\n".join([f"{m.get('user')}: {m.get('text')}" for m in messages])

        # AI Analysis
        analysis = ai_service.analyze_thread(full_text)
        
        # Reply
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            blocks=get_ai_summary_block(analysis),
            text="Here is the analysis of the discussion."
        )
        client.reactions_add(channel=channel_id, name="white_check_mark", timestamp=event["ts"])

    except Exception as e:
        logger.error(f"Error analyzing thread: {e}")
        say(f"Sorry, I stumbled while analyzing that: {str(e)}")
    finally:
        client.reactions_remove(channel=channel_id, name="eyes", timestamp=event["ts"])

# --- 3. ACTIVE PERSISTENCE (Nudge Command) ---
@app.command("/evidently-nudge")
def trigger_nudge(ack, body, client):
    """
    Identifies stale assumptions (older than 14 days) and prompts the team.
    """
    ack()
    user_id = body["user_id"]
    
    # 1. Fetch Stale Data via DB Service
    # In a real scenario, db_service.get_stale_assumptions() checks 'last_verified_at'
    stale_assumptions = db_service.get_stale_assumptions(days=14)
    
    if not stale_assumptions:
        client.chat_postEphemeral(
            channel=body['channel_id'], 
            user=user_id, 
            text="🌱 Everything is fresh! No stale assumptions found."
        )
        return

    # 2. Build Interactive Nudge Message
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "⏰ Time to Revisit"}
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn", 
                "text": "The following assumptions haven't been tested in 2 weeks. "
                        "According to the *Test & Learn framework*, we should validate or archive them."
            }
        }
    ]

    for assump in stale_assumptions:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn", 
                "text": f"> *{assump['text']}*\n_Confidence: {assump['confidence']}%_"
            },
            "accessory": {
                "type": "overflow",
                "options": [
                    {"text": {"type": "plain_text", "text": "Generate Experiment"}, "value": f"gen_{assump['id']}"},
                    {"text": {"type": "plain_text", "text": "Mark Validated"}, "value": f"val_{assump['id']}"},
                    {"text": {"type": "plain_text", "text": "Archive"}, "value": f"arch_{assump['id']}"}
                ],
                "action_id": "nudge_action"
            }
        })

    client.chat_postMessage(channel=user_id, blocks=blocks)

# --- 4. ACTION HANDLERS (Interactivity) ---
@app.action("keep_assumption")
def handle_keep(ack, body, client, logger):
    ack()
    try:
        user_id = body['user']['id']
        assumption_id = body['actions'][0]['value']
        
        db_service.update_assumption_status(assumption_id, "active")
        
        client.chat_postMessage(channel=user_id, text=f"✅ Assumption {assumption_id} marked as active.")
    except Exception as e:
        logger.error(f"Error in handle_keep action: {e}")

@app.action("archive_assumption")
def handle_archive(ack, body, client, logger):
    ack()
    try:
        user_id = body['user']['id']
        assumption_id = body['actions'][0]['value']
        
        db_service.update_assumption_status(assumption_id, "archived")
        
        client.chat_postMessage(channel=user_id, text=f"🗑️ Assumption {assumption_id} archived.")
    except Exception as e:
        logger.error(f"Error in handle_archive action: {e}")

@app.action("gen_experiment_modal")
def handle_gen_experiment(ack, body, client, logger):
    """Generates AI experiment suggestions for an assumption"""
    ack()
    try:
        assumption_text = body['actions'][0]['value']
        trigger_id = body['trigger_id']

        # AI Generation
        suggestions = ai_service.generate_experiment_suggestions(assumption_text)

        # Open Modal with results
        client.views_open(
            trigger_id=trigger_id,
            view={
                "type": "modal",
                "title": {"type": "plain_text", "text": "Experiment Ideas"},
                "blocks": [
                    {"type": "section", "text": {"type": "mrkdwn", "text": f"Suggestions for: *{assumption_text}*"}},
                    {"type": "divider"},
                    {"type": "section", "text": {"type": "mrkdwn", "text": suggestions}}
                ]
            }
        )
    except Exception as e:
        logger.error(f"Error in handle_gen_experiment action: {e}")
        
# --- 5. START ---
if __name__ == "__main__":
    handler = SocketModeHandler(app, Config.SLACK_APP_TOKEN)
    handler.start()
