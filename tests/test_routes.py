import logging
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from slack_bolt import App

from controllers.web_controller import create_web_app


class DummyDbService:
    def consume_oauth_state(self, _state: str):
        return None


class DummyGoogleService:
    def get_tokens_from_code(self, _code: str):
        return {}


async def dummy_asana_webhook(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


def _make_app():
    dummy_slack_app = App(
        signing_secret="dummy-secret",
        token="xoxb-dummy-token",
        token_verification_enabled=False,
    )
    return create_web_app(
        db_service=DummyDbService(),
        google_service=DummyGoogleService(),
        handle_asana_webhook=dummy_asana_webhook,
        logger=logging.getLogger("test"),
        slack_app=dummy_slack_app,
    )


@pytest.mark.asyncio
async def test_google_callback_missing_params_returns_400():
    app = _make_app()
    server = TestServer(app)
    async with TestClient(server) as client:
        resp = await client.get("/auth/callback/google")
        assert resp.status == 400


@pytest.mark.asyncio
async def test_slack_events_route_exists():
    """POST /slack/events should not return 404."""
    app = _make_app()
    server = TestServer(app)
    async with TestClient(server) as client:
        resp = await client.post("/slack/events", json={})
        assert resp.status != 404
