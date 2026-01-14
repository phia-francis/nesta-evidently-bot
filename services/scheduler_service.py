import logging
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from slack_sdk.errors import SlackApiError


def update_all_dashboards(client, db_service, ui_manager) -> None:  # noqa: ANN001
    projects = db_service.get_projects_with_dashboard_message_ts()
    for project in projects:
        channel_id = project.get("channel_id")
        message_ts = project.get("dashboard_message_ts")
        if not channel_id or not message_ts:
            continue
        try:
            metrics = db_service.get_metrics(project["id"])
            view = ui_manager.get_home_view(
                project.get("created_by", ""),
                project,
                [
                    {
                        "name": project.get("name", "Project"),
                        "id": project["id"],
                    }
                ],
                active_tab="overview",
                metrics=metrics,
            )
            client.chat_update(
                channel=channel_id,
                ts=message_ts,
                blocks=view.get("blocks", []),
                text=f"📊 Daily update for {project.get('name', 'project')}",
            )
        except SlackApiError as exc:
            logging.warning("Failed to update dashboard for project %s: %s", project.get("id"), exc)
        except Exception:
            logging.exception("Unexpected error updating dashboard for project %s", project.get("id"))


def start_scheduler(client, db_service, ui_manager) -> BackgroundScheduler:  # noqa: ANN001
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        update_all_dashboards,
        "cron",
        hour=9,
        minute=0,
        args=[client, db_service, ui_manager],
    )
    scheduler.start()
    return scheduler
