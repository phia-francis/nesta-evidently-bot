from enum import Enum

from slack_sdk.models.blocks import InputBlock
from slack_sdk.models.blocks.block_elements import PlainTextInputElement, RadioButtonsElement
from slack_sdk.models.objects import Option, PlainTextObject

from blocks.nesta_ui import NestaUI


class ProjectPhase(Enum):
    DISCOVERY = ("Discovery (Understanding needs)", "Discovery")
    ALPHA = ("Alpha (Testing solutions)", "Alpha")
    BETA = ("Beta (Scaling)", "Beta")

    def __init__(self, display_text: str, value: str) -> None:
        self.display_text = display_text
        self.value = value


def get_onboarding_welcome() -> dict:
    return {
        "type": "home",
        "blocks": [
            NestaUI.header("Welcome to Evidently"),
            NestaUI.section("The innovation copilot for mission-driven teams."),
            NestaUI.divider(),
            NestaUI.section(
                "*Let's get you set up.*\n"
                "Evidently helps you track risks, run experiments, and make evidence-based decisions.\n\n"
                "To begin, we need to define your *Mission*."
            ),
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "🚀 Start New Project"},
                        "style": "primary",
                        "action_id": "setup_step_1",
                    }
                ],
            },
            NestaUI.tip_panel("Innovation starts with a clear definition of the problem, not the solution."),
        ],
    }


def get_setup_step_1_modal() -> dict:
    return {
        "type": "modal",
        "callback_id": "setup_step_2_submit",
        "title": {"type": "plain_text", "text": "Step 1: The Problem"},
        "blocks": [
            NestaUI.progress_bar(1, 3),
            NestaUI.section("Every great project solves a real problem. Describe it simply."),
            InputBlock(
                block_id="problem_block",
                label={"type": "plain_text", "text": "Problem Statement"},
                element=PlainTextInputElement(
                    action_id="problem_input",
                    multiline=True,
                    placeholder="e.g. 'Local councils struggle to track carbon emissions because...'",
                ),
            ).to_dict(),
            NestaUI.tip_panel("Keep it user-centric. Avoid mentioning technology yet."),
        ],
        "submit": {"type": "plain_text", "text": "Next: The Goal →"},
    }


def get_setup_step_2_modal(problem_statement: str) -> dict:
    return {
        "type": "modal",
        "callback_id": "setup_final_submit",
        "private_metadata": problem_statement,
        "title": {"type": "plain_text", "text": "Step 2: The Goal"},
        "blocks": [
            NestaUI.progress_bar(2, 3),
            NestaUI.section(f"You're solving: _{problem_statement}_"),
            InputBlock(
                block_id="name_block",
                label={"type": "plain_text", "text": "Project Name"},
                element=PlainTextInputElement(action_id="name_input"),
            ).to_dict(),
            InputBlock(
                block_id="phase_block",
                label={"type": "plain_text", "text": "Current Phase"},
                element=RadioButtonsElement(
                    action_id="phase_input",
                    options=[
                        Option(text=PlainTextObject(text=phase.display_text), value=phase.value)
                        for phase in ProjectPhase
                    ],
                ),
            ).to_dict(),
        ],
        "submit": {"type": "plain_text", "text": "✨ Launch Project"},
    }
