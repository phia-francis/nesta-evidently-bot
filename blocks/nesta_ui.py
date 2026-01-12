from slack_sdk.models.blocks import ContextBlock, DividerBlock, HeaderBlock, ImageBlock, SectionBlock

from config import Config


class NestaUI:
    """
    UI Design System for the Slack Bot.
    Enforces Nesta branding: Professional, Clear, Evidence-Based.
    """

    @staticmethod
    def header(text: str) -> dict:
        return HeaderBlock(text=text).to_dict()

    @staticmethod
    def section(text: str, accessory=None) -> dict:
        return SectionBlock(text=text, accessory=accessory).to_dict()

    @staticmethod
    def divider() -> dict:
        return DividerBlock().to_dict()

    @staticmethod
    def tip_panel(text: str) -> dict:
        return ContextBlock(
            elements=[
                ImageBlock(image_url=Config.NESTA_TIP_ICON_URL, alt_text="idea").to_dict(),
                {"type": "mrkdwn", "text": f"*Nesta Tip:* {text}"},
            ]
        ).to_dict()

    @staticmethod
    def context(text: str) -> dict:
        return ContextBlock(elements=[{"type": "mrkdwn", "text": text}]).to_dict()

    @staticmethod
    def progress_bar(current: int, total: int) -> dict:
        filled = "⬛"
        empty = "⬜"
        bar = filled * current + empty * (total - current)
        return ContextBlock(elements=[{"type": "mrkdwn", "text": f"Setup Progress: {bar} ({current}/{total})"}]).to_dict()

    @staticmethod
    def method_card(method: dict) -> list[dict]:
        return [
            SectionBlock(
                text=(
                    f"*{method['icon']} {method['name']}*\n"
                    f"Difficulty: `{method['difficulty']}` | Strength: `{method['evidence_strength']}`\n"
                    f"{method['description']}"
                )
            ).to_dict(),
            ContextBlock(elements=[{"type": "mrkdwn", "text": f"🎯 *Best for:* {', '.join(method['best_for']).title()}"}]).to_dict(),
        ]
