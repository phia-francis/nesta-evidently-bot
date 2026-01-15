import asyncio
import threading

from aiohttp import web
from slack_bolt.adapter.socket_mode import SocketModeHandler

from config import Config
from controllers.slack_controller import app as slack_app
from controllers.slack_controller import db_service, google_service, handle_asana_webhook, logger
from controllers.web_controller import create_web_app


def start_web_server() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    web_app = create_web_app(
        db_service=db_service,
        google_service=google_service,
        handle_asana_webhook=handle_asana_webhook,
        logger=logger,
    )
    runner = web.AppRunner(web_app)
    loop.run_until_complete(runner.setup())
    site = web.TCPSite(runner, host=Config.HOST, port=Config.PORT)
    loop.run_until_complete(site.start())
    loop.run_forever()


if __name__ == "__main__":
    web_thread = threading.Thread(target=start_web_server, daemon=True)
    web_thread.start()

    handler = SocketModeHandler(slack_app, Config.SLACK_APP_TOKEN)
    handler.start()
