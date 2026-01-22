import logging
import os
from enum import Enum

from cryptography.fernet import Fernet
from dotenv import load_dotenv


def get_encryption_key() -> bytes | None:
    key = os.environ.get("GOOGLE_TOKEN_ENCRYPTION_KEY")
    environment = os.environ.get("ENVIRONMENT", "development").lower()
    if not key:
        if environment == "production":
            raise RuntimeError("GOOGLE_TOKEN_ENCRYPTION_KEY must be set in production.")
        logging.warning("GOOGLE_TOKEN_ENCRYPTION_KEY is not set; Google tokens will be stored in plaintext.")
        return None
    try:
        key_bytes = key.encode("utf-8")
        Fernet(key_bytes)
        return key_bytes
    except ValueError:  # noqa: BLE001
        if environment == "production":
            raise RuntimeError("GOOGLE_TOKEN_ENCRYPTION_KEY is invalid in production.")
        logging.warning("GOOGLE_TOKEN_ENCRYPTION_KEY is invalid; Google tokens will be stored in plaintext.")
        return None

load_dotenv()


class Config:
    ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")
    SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
    SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET")
    SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")
    SLACK_APP_ID = os.environ.get("SLACK_APP_ID")
    GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
    GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI")
    ASANA_TOKEN = os.environ.get("ASANA_TOKEN")
    ASANA_WORKSPACE_ID = os.environ.get("ASANA_WORKSPACE_ID")
    # Standard Database URL (default to local SQLite for dev)
    DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./evidently.db")
    GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    GOOGLE_TOKEN_ENCRYPTION_KEY = get_encryption_key()
    OAUTH_STATE_TTL_SECONDS = int(os.environ.get("OAUTH_STATE_TTL_SECONDS", 600))
    PORT = int(os.environ.get("PORT", 10000))
    OAUTH_PORT = int(os.environ.get("OAUTH_PORT", 10001))
    HOST = os.environ.get("HOST", "0.0.0.0")
    LEADERSHIP_CHANNEL = os.environ.get("LEADERSHIP_CHANNEL", "#leadership-updates")
    STANDUP_ENABLED = os.environ.get("STANDUP_ENABLED", "false").lower() == "true"
    STANDUP_HOUR = int(os.environ.get("STANDUP_HOUR", 9))
    STANDUP_MINUTE = int(os.environ.get("STANDUP_MINUTE", 30))
    BACKUP_ENABLED = os.environ.get("BACKUP_ENABLED", "false").lower() == "true"
    BACKUP_CHANNEL = os.environ.get("BACKUP_CHANNEL", "")
    ADMIN_USERS = [user_id.strip() for user_id in os.environ.get("ADMIN_USERS", "").split(",") if user_id.strip()]

    # Thresholds
    CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", 0.8))
    STALE_DAYS = int(os.environ.get("STALE_DAYS", 14))
    NESTA_TIP_ICON_URL = os.environ.get("NESTA_TIP_ICON_URL", "https://emojicdn.elk.sh/💡")
    AI_CANVAS_FALLBACK = os.environ.get(
        "AI_CANVAS_FALLBACK",
        "We need to validate this area with more evidence.",
    )
    AI_EXPERIMENT_FALLBACK = os.environ.get(
        "AI_EXPERIMENT_FALLBACK",
        "Unable to generate experiments right now.",
    )


class Brand:
    """Nesta brand palette and semantic helpers (immutable constants)."""

    # Core Palette
    NESTA_BLUE = "#0000FF"
    NESTA_NAVY = "#0F294A"
    NESTA_TEAL = "#0FA3A4"
    NESTA_AMBER = "#FFB703"
    NESTA_RED = "#EB003B"
    NESTA_AQUA = "#97D9E3"
    NESTA_PURPLE = "#9A1BBE"

    # OCP Semantic Mapping
    COLOR_OPPORTUNITY = NESTA_AMBER
    COLOR_CAPABILITY = NESTA_TEAL
    COLOR_PROGRESS = NESTA_NAVY

    # Fonts (Image generation only)
    FONT_HEADLINE = "Zosia Display"
    FONT_BODY = "Averta"


class Category(Enum):
    OPPORTUNITY = "opportunity"
    CAPABILITY = "capability"
    PROGRESS = "progress"
