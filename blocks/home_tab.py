import logging
from config import Brand
# Assuming chart_service is created as per architectural plan
from services.chart_service import ChartService 

logger = logging.getLogger(__name__)

# Constants for UI Text
NO_ASSUMPTIONS_TEXT = "_No assumptions logged yet. What risks are we taking?_"
SECTION_DIVIDER = {"type": "divider"}

def _get_confidence_emoji(score):
    """Returns a visual indicator based on confidence score."""
    if score >= 80:
        return "🟢" # High confidence
    elif score >= 50:
        return "🟡" # Needs validation
    return "🔴"     # Critical assumption (Low confidence)

def _generate_assumption_row(assumption):
    """
    Creates a detailed row for a single assumption.
    Uses 'context' blocks to display metadata (confidence/status) subtly.
    """
    status_icon = "❄️" if assumption.get('status') == 'stale' else "🔥"
    conf_emoji = _get_confidence_emoji(assumption.get('confidence', 0))
    
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{conf_emoji} *{assumption['text']}*"
            },
            "accessory": {
                "type": "overflow",
                "action_id": "assumption_overflow",
                "options": [
                    {"text": {"type": "plain_text", "text": "View Evidence"}, "value": f"view_{assumption['id']}"},
                    {"text": {"type": "plain_text", "text": "Generate Test"}, "value": f"test_{assumption['id']}"},
                    {"text": {"type": "plain_text", "text": "Archive"}, "value": f"archive_{assumption['id']}"}
                ]
            }
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"Confidence: *{assumption.get('confidence', 0)}%*"},
                {"type": "mrkdwn", "text": f"| Status: {status_icon} {assumption.get('status', 'active').title()}"},
                {"type": "mrkdwn", "text": f"| Uploaded: {assumption.get('date_logged', 'Unknown')}"}
            ]
        }
    ]

def get_home_view(user_id, project_data):
    """
    Generates the Home Tab JSON payload.
    Features:
    1. Dynamic Progress Ring (Visual Identity).
    2. OCP Framework Sections.
    3. Active Experiment Monitors.
    """
    blocks = []
    
    # Extract Data
    assumptions = project_data.get('assumptions', [])
    experiments = project_data.get('experiments', [])
    progress_score = project_data.get('progress_score', 0) # Calculated aggregate score
    
    # --- 1. HEADER & VISUAL DASHBOARD ---
    # We generate a dynamic chart URL on the fly
    try:
        chart_url = ChartService.generate_progress_ring(progress_score, "Confidence")
    except Exception as e:
        logger.error(f"Chart generation failed: {e}")
        chart_url = "https://via.placeholder.com/300?text=Evidently" # Fallback

    blocks.extend([
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"👋 *Welcome, <@{user_id}>.*\n\n"
                    f"You are viewing: *{project_data.get('name', 'General Project')}*\n"
                    f"Current Phase: *{project_data.get('phase', 'Discovery')}*"
                )
            },
            "accessory": {
                "type": "image",
                "image_url": chart_url,
                "alt_text": "Project Confidence Score"
            }
        },
        {"type": "actions", "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "New Assumption", "emoji": True},
                "style": "primary",
                "action_id": "open_new_assumption_modal"
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Sync Evidence", "emoji": True},
                "action_id": "trigger_evidence_sync"
            }
        ]},
        SECTION_DIVIDER
    ])

    # --- 2. OCP FRAMEWORK GRID ---
    
    categories = [
        ("🎯 Opportunity (Value)", "opportunity", "Do users want this?"),
        ("⚙️ Capability (Feasibility)", "capability", "Can we build this?"),
        ("📈 Progress (Sustainability)", "progress", "Is it working?")
    ]

    for title, cat_key, prompt in categories:
        # Filter assumptions for this category
        cat_assumptions = [a for a in assumptions if a['category'] == cat_key]
        
        # Section Header
        blocks.append({
            "type": "header", 
            "text": {"type": "plain_text", "text": title}
        })
        
        # Render Assumptions or Empty State
        if not cat_assumptions:
             blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"_{prompt}_"},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "+ Add"},
                    "action_id": f"add_{cat_key}",
                    "value": cat_key
                }
            })
        else:
            for assump in cat_assumptions[:3]: # Limit to top 3 to save space
                blocks.extend(_generate_assumption_row(assump))
            
            if len(cat_assumptions) > 3:
                blocks.append({
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": f"And {len(cat_assumptions) - 3} more..."}]
                })

    blocks.append(SECTION_DIVIDER)

    # --- 3. ACTIVE EXPERIMENTS MONITOR ---
    blocks.append({
        "type": "header",
        "text": {"type": "plain_text", "text": "⚗️ Active Experiments"}
    })

    if not experiments:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "No experiments running. *Turn a low-confidence assumption into a test.*"}
        })
    else:
        for exp in experiments:
            # Simulate a status check logic
            is_success = exp.get('current_metric', 0) >= exp.get('target_metric', 100)
            status_emoji = "✅" if is_success else "⚠️"
            
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*{exp['name']}*\n"
                        f"Target: {exp['metric']} > {exp['target_metric']}\n"
                        f"Current: *{exp.get('current_metric', 0)}* {status_emoji}"
                    )
                },
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Analyze", "emoji": True},
                    "style": "primary" if is_success else "danger",
                    "value": exp['id'],
                    "action_id": "analyze_experiment_results"
                }
            })

    # --- 4. FOOTER ---
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "image",
                "image_url": "https://nesta-logo-url.com/favicon.png", # Replace with actual hosted Nesta asset
                "alt_text": "Nesta"
            },
            {"type": "mrkdwn", "text": "Powered by *Evidently* | Nesta's Test & Learn Toolkit"}
        ]
    })

    return {
        "type": "home",
        "blocks": blocks
    }
