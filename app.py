import asyncio
import os

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
        slack_app=slack_app,
    )


async def run_schema_check() -> None:
    await asyncio.to_thread(check_and_update_schema)


if __name__ == "__main__":
    Config.validate()

    print("🔧 Checking database schema...")
    asyncio.run(run_schema_check())

    if os.environ.get("USE_SOCKET_MODE", "false").lower() == "true":
        SocketModeHandler(slack_app, Config.SLACK_APP_TOKEN).start()
    else:
        web.run_app(create_app(), host=Config.HOST, port=Config.PORT)
