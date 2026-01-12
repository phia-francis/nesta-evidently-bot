from dataclasses import dataclass

from config import Config


@dataclass(frozen=True)
class ConfigManager:
    """Validate environment configuration at startup."""

    required_keys: tuple[str, ...] = (
        "SLACK_BOT_TOKEN",
        "SLACK_SIGNING_SECRET",
        "SLACK_APP_TOKEN",
        "GOOGLE_API_KEY",
    )

    def validate(self) -> None:
        missing = [key for key in self.required_keys if not getattr(Config, key, None)]
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
