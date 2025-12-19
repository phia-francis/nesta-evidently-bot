def get_home_view(project_data):
    assumptions = project_data.get('assumptions', [])
    experiments = project_data.get('experiments', [])
    
    # Helper to filter assumptions by category
    def get_by_cat(cat):
        return [f"• {a['text']} ({a['status']})" for a in assumptions if a['category'] == cat]

    opps = "\n".join(get_by_cat(OPPORTUNITY_CATEGORY)) or NO_ASSUMPTIONS_TEXT
    caps = "\n".join(get_by_cat(CAPABILITY_CATEGORY)) or NO_ASSUMPTIONS_TEXT
    prog = "\n".join(get_by_cat(PROGRESS_CATEGORY)) or NO_ASSUMPTIONS_TEXT

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Evidently Dashboard: {project_data.get('name', 'Unnamed Project')}"}
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Current Focus:* Validating user intake pathways."}
        },
        {"type": "divider"},
        # OCP Grid Visualization
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "🎯 Opportunity (Value)"}
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": opps}
        },
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "⚙️ Capability (Feasibility)"}
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": caps}
        },
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "📈 Progress (Sustainability)"}
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": prog}
        },
        {"type": "divider"},
        # Active Experiments Section
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "⚗️ Active Experiments"}
        },
    ]

    if experiments:
        exp = experiments[0]
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{exp['name']}*\nMetric: {exp['metric']}"},
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "View Results"},
                "action_id": "view_experiment_results"
            }
        })
    else:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "No active experiments."}
        })

    return {
        "type": "home",
        "blocks": blocks
    }
