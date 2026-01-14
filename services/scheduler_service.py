import logging
import os
from typing import TYPE_CHECKING, Type

from apscheduler.schedulers.background import BackgroundScheduler
from slack_sdk.errors import SlackApiError

if TYPE_CHECKING:
    from slack_sdk.web.client import WebClient

    from blocks.ui_manager import UIManager
    from services.db_service import DbService


def update_all_dashboards(
    client: "WebClient",
    db_service: "DbService",
    ui_manager: Type["UIManager"],
) -> None:
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
        except (KeyError, TypeError, ValueError) as exc:
            logging.warning(
                "Failed to build dashboard update for project %s: %s",
                project.get("id"),
                exc,
            )


def broadcast_weekly_wins(
    client: "WebClient",
    db_service: "DbService",
) -> None:
    channel_id = os.environ.get("PUBLIC_WINS_CHANNEL")
    if not channel_id:
        logging.info("PUBLIC_WINS_CHANNEL not set; skipping weekly wins broadcast.")
        return
    experiments = db_service.get_recent_experiment_outcomes(days=7)
    if not experiments:
        logging.info("No recent experiment outcomes to broadcast.")
        return
    lines = []
    for experiment in experiments:
        outcome = experiment.get("outcome", "Validated").lower()
        lines.append(
            f"🎉 *Weekly Learning Log:* {experiment['project_name']} {outcome} {experiment['hypothesis']}!"
        )
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}}]
    try:
        client.chat_postMessage(
            channel=channel_id,
            blocks=blocks,
            text="🎉 Weekly Learning Log updates",
        )
    except SlackApiError as exc:
        logging.warning("Failed to broadcast weekly wins: %s", exc)


def nudge_stale_projects(
    client: "WebClient",
    db_service: "DbService",
) -> None:
    stale_projects = db_service.get_stale_projects(days=14)
    if not stale_projects:
        logging.info("No stale projects found for nudges.")
        return
    for project in stale_projects:
        owner_id = project.get("created_by")
        if not owner_id:
            continue
        try:
            client.chat_postMessage(
                channel=owner_id,
                text=(
                    f"👋 Checking in on *{project.get('name', 'your project')}*.\n"
                    "It's been 2 weeks. Has your understanding of the risks changed?"
                ),
            )
        except SlackApiError as exc:
            logging.warning("Failed to nudge project owner %s: %s", owner_id, exc)


def start_scheduler(
    client: "WebClient",
    db_service: "DbService",
    ui_manager: Type["UIManager"],
) -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        update_all_dashboards,
        "cron",
        hour=9,
        minute=0,
        args=[client, db_service, ui_manager],
    )
    scheduler.add_job(
        broadcast_weekly_wins,
        "cron",
        day_of_week="mon",
        hour=9,
        minute=30,
        args=[client, db_service],
    )
    scheduler.add_job(
        nudge_stale_projects,
        "cron",
        hour=10,
        minute=0,
        args=[client, db_service],
    )
    scheduler.start()
    return scheduler
