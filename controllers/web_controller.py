import asyncio
import json
from typing import Callable

from aiohttp import web
from slack_bolt import App
from slack_bolt.adapter.aiohttp import AsyncBoltRequest, to_aiohttp_response
from sqlalchemy.exc import SQLAlchemyError

from services.db_service import DbService
from services.google_service import GoogleService


def create_web_app(
    db_service: DbService,
    google_service: GoogleService,
    handle_asana_webhook: Callable[[web.Request], web.Response],
    logger,
    slack_app: App,
) -> web.Application:
    web_app = web.Application()

    async def slack_events_handler(request: web.Request) -> web.Response:
        """Intercept URL verification before Bolt signature checking, then delegate."""
        try:
            body = await request.text()

            try:
                payload = json.loads(body)
                if payload.get("type") == "url_verification":
                    return web.Response(text=payload["challenge"], content_type="text/plain")
            except json.JSONDecodeError:
                pass

            # Pass pre-read body to Bolt since the stream is already consumed
            bolt_req = AsyncBoltRequest(body=body, query=request.query_string, headers=request.headers)
            bolt_resp = await asyncio.to_thread(slack_app.dispatch, bolt_req)
            return await to_aiohttp_response(bolt_resp)

        except Exception:
            logger.exception("Error handling Slack event")
            return web.Response(text="Internal Server Error", status=500)

    async def health_check(request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def google_callback(request: web.Request) -> web.Response:
        code = request.query.get("code")
        state = request.query.get("state")
        if not code or not state:
            return web.Response(text="Missing code or state.", status=400)
        oauth_payload = await asyncio.to_thread(db_service.consume_oauth_state, state)
        if not oauth_payload:
            return web.Response(text="Invalid state.", status=400)
        project_id = oauth_payload["project_id"]
        try:
            token_response = await asyncio.to_thread(google_service.get_tokens_from_code, code)
            project = await asyncio.to_thread(db_service.get_project, project_id)
            if not project:
                return web.Response(text="Project not found.", status=404)
            integrations = project.get("integrations") or {}
            drive_settings = dict(integrations.get("drive") or {})
            await asyncio.to_thread(
                db_service.update_google_tokens,
                project_id,
                token_response.get("access_token"),
                token_response.get("refresh_token"),
                token_response.get("expires_in"),
            )
            drive_settings.update({"connected": True})
            integrations["drive"] = drive_settings
            await asyncio.to_thread(db_service.update_project_integrations, project_id, integrations)
            return web.Response(
                text="<h1>Success! Drive Connected.</h1>",
                status=200,
                content_type="text/html",
            )
        except (ValueError, SQLAlchemyError):
            logger.exception("Google OAuth callback failed")
            return web.Response(text="Connection failed.", status=500)

    web_app.router.add_get("/", health_check)
    web_app.router.add_get("/healthz", health_check)
    web_app.router.add_post("/slack/events", slack_events_handler)
    web_app.router.add_post("/asana/webhook", handle_asana_webhook)
    web_app.router.add_get("/auth/callback/google", google_callback)
    return web_app
