def get_home_view(user_name, project_data):
    assumptions = project_data.get('assumptions', [])
    experiments = project_data.get('experiments', [])
    
    # Helper to filter assumptions by category
    def get_by_cat(cat):
        return [f"• {a['text']} ({a['status']})" for a in assumptions if a['category'] == cat]

    opps = "\n".join(get_by_cat("Opportunity")) or "No active assumptions."
    caps = "\n".join(get_by_cat("Capability")) or "No active assumptions."
    prog = "\n".join(get_by_cat("Progress")) or "No active assumptions."

    return {
        "type": "home",
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"Evidently Dashboard: {project_data['name']}"}
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
             {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{experiments[0]['name']}*\nMetric: {experiments[0]['metric']}"},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View Results"},
                    "action_id": "view_experiment_results"
                }
            }
        ]
    }
