import random


class PlaybookService:
    """
    The digital brain of the Nesta Test & Learn Playbook.
    Maps assumptions to methods and provides educational content.
    """

    def __init__(self):
        self.methods = {
            "interview": {
                "name": "User Interviews",
                "icon": "🗣️",
                "difficulty": "Low",
                "evidence_strength": "Low (Qualitative)",
                "description": "One-on-one conversations to understand user needs, pains, and goals.",
                "best_for": ["desirability", "problem_validation"],
                "nesta_tip": (
                    "Don't ask 'Would you use this?' Ask 'When was the last time you solved this problem?'"
                    " (The Mom Test)."
                ),
            },
            "fake_door": {
                "name": "Fake Door (Smoke Test)",
                "icon": "🚪",
                "difficulty": "Medium",
                "evidence_strength": "High (Behavioral)",
                "description": (
                    "Create a landing page or button for a feature that doesn't exist yet to measure click-through "
                    "intent."
                ),
                "best_for": ["desirability", "demand"],
                "nesta_tip": "Always inform the user afterwards that this was a test and offer to notify them when it launches.",
            },
            "concierge": {
                "name": "Concierge MVP",
                "icon": "🛎️",
                "difficulty": "High",
                "evidence_strength": "Very High",
                "description": "Manually performing the service for the user (behind the scenes) instead of building code.",
                "best_for": ["viability", "feasibility"],
                "nesta_tip": "Focus on learning the process flows before automating them.",
            },
            "pre_mortem": {
                "name": "Pre-Mortem",
                "icon": "💀",
                "difficulty": "Low",
                "evidence_strength": "Medium (Strategic)",
                "description": (
                    "Assume the project has failed 6 months from now. Work backwards to determine what went wrong."
                ),
                "best_for": ["risk", "feasibility"],
                "nesta_tip": "This helps break 'groupthink' and allows team members to voice concerns safely.",
            },
            "wizard_of_oz": {
                "name": "Wizard of Oz",
                "icon": "🧙‍♂️",
                "difficulty": "High",
                "evidence_strength": "High",
                "description": "The front-end looks real, but humans are doing the work on the back-end.",
                "best_for": ["feasibility", "viability"],
                "nesta_tip": "Great for testing complex AI or algo-driven ideas without writing the algo.",
            },
        }

    def get_recommendations(self, category: str):
        return [
            {**method_data, "id": method_id}
            for method_id, method_data in self.methods.items()
            if category in method_data["best_for"]
        ]

    def get_method_details(self, method_id: str):
        return self.methods.get(method_id)

    def get_random_tip(self):
        tips = [
            "Fall in love with the problem, not the solution.",
            "Evidence beats opinion. Data beats arguments.",
            "Test your riskiest assumption first.",
            "Fail fast, learn faster.",
        ]
        return random.choice(tips)
