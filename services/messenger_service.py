import logging
from typing import Any

logger = logging.getLogger(__name__)


class MessengerService:
    """Standardized Slack messaging wrapper with error logging."""

    def __init__(self, client) -> None:  # noqa: ANN001
        self.client = client

    def post_message(self, channel: str, text: str, blocks: list[dict[str, Any]] | None = None) -> None:
        try:
            self.client.chat_postMessage(channel=channel, text=text, blocks=blocks)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to post message")

    def post_ephemeral(self, channel: str, user: str, text: str, blocks: list[dict[str, Any]] | None = None) -> None:
        try:
            self.client.chat_postEphemeral(channel=channel, user=user, text=text, blocks=blocks)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to post ephemeral message")

    def upload_file(self, channel: str, file, filename: str, title: str, comment: str) -> None:  # noqa: ANN001
        try:
            self.client.files_upload_v2(
                channel=channel,
                file=file,
                filename=filename,
                title=title,
                initial_comment=comment,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to upload file")
