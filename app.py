import asyncio
import os
import threading

from aiohttp import web
from slack_bolt.adapter.socket_mode import SocketModeHandler

from config import Config
from controllers.slack_controller import app as slack_app
from controllers.slack_controller import db_service, google_service, handle_asana_webhook, logger
from controllers.web_controller import create_web_app
from services.schema_fixer import check_and_update_schema


def create_app() -> web.Application:
    return create_web_app(
        db_service=db_service,
        google_service=google_service,
        handle_asana_webhook=handle_asana_webhook,
        logger=logger,
    )


def start_slack_handler() -> None:
    handler = SocketModeHandler(slack_app, Config.SLACK_APP_TOKEN)
    handler.start()


if __name__ == "__main__":
    print("🔧 Checking database schema...")
    check_and_update_schema()

    slack_thread = threading.Thread(target=start_slack_handler, daemon=True)
    slack_thread.start()

    app = create_app()
    web.run_app(app, host=Config.HOST, port=Config.PORT)
