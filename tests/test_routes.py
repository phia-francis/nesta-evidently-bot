import logging
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from controllers.web_controller import create_web_app


class DummyDbService:
    def consume_oauth_state(self, _state: str):
        return None


class DummyGoogleService:
    def get_tokens_from_code(self, _code: str):
        return {}


async def dummy_asana_webhook(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


@pytest.mark.asyncio
async def test_google_callback_missing_params_returns_400():
    app = create_web_app(
        db_service=DummyDbService(),
        google_service=DummyGoogleService(),
        handle_asana_webhook=dummy_asana_webhook,
        logger=logging.getLogger("test"),
    )
    server = TestServer(app)
    async with TestClient(server) as client:
        resp = await client.get("/auth/callback/google")
        assert resp.status == 400
