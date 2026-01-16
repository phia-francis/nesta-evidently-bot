import json
import random
from pathlib import Path


class PlaybookService:
    """
    The digital brain of the Nesta Test & Learn Playbook.
    Maps assumptions to methods and provides educational content.
    """

    def __init__(self):
        self.methods = self._load_methods()
        self.ocp_questions = {
            "Opportunity": {
                "Needs": "Who is the end user? What pain points does this solve?",
                "Market": "What is the target market size? What are the barriers to entry?",
                "Rules": "Does this infringe on IP? What regulations apply?",
            },
            "Progress": {
                "Approach": "What is the USP? How does it create value?",
                "Impact": "What are the economic/social/environmental impacts?",
            },
            "Capability": {
                "Leadership": "Who are the champions? Is management expertise in place?",
                "Finance": "Do we have funding/runway? What is the cost to develop?",
                "Operations": "Do we have the right skills and partners?",
            },
        }
        self.roadmap_horizons = [
            {
                "key": "now",
                "label": "NOW (Alpha)",
                "description": "Validating the Concept. (Focus: Desirability, Viability).",
            },
            {
                "key": "next",
                "label": "NEXT (Beta)",
                "description": "Validating Growth. (Focus: Scalable channels, Retention).",
            },
            {
                "key": "later",
                "label": "LATER (Scale)",
                "description": "Validating System Change. (Focus: Institutional adoption).",
            },
        ]
        self.test_and_learn_phases = [
            {
                "key": "define",
                "label": "DEFINE",
                "title": "Set direction.",
                "activities": ["Map stakeholder needs", "Evidence reviews"],
            },
            {
                "key": "shape",
                "label": "SHAPE SYSTEMS",
                "title": "Enable environment.",
                "activities": ["Remove bureaucratic blockers", "Secure resources"],
            },
            {
                "key": "develop",
                "label": "DEVELOP",
                "title": "Create solutions.",
                "activities": ["Low-fidelity prototypes", "Policy blueprints"],
            },
            {
                "key": "test",
                "label": "TEST & LEARN",
                "title": "Iterative loop.",
                "activities": ["Design rapid experiments (Fake Door, Wizard of Oz)"],
            },
            {
                "key": "diffuse",
                "label": "DIFFUSE",
                "title": "Expand impact.",
                "activities": ["Codify knowledge", "Integrate into 'Business as Usual'"],
            },
        ]

    def _load_methods(self) -> dict:
        methods_path = Path(__file__).with_name("playbook_methods.json")
        with methods_path.open(encoding="utf-8") as handle:
            return json.load(handle)

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

    def get_ocp_questions(self) -> dict[str, dict[str, str]]:
        return self.ocp_questions

    def get_roadmap_horizons(self) -> list[dict[str, str]]:
        return self.roadmap_horizons

    def get_test_and_learn_phases(self) -> list[dict[str, object]]:
        return self.test_and_learn_phases

    def get_phase_details(self, phase_key: str) -> dict[str, object]:
        normalized_key = (phase_key or "").strip().lower()
        for phase in self.test_and_learn_phases:
            if phase["key"] == normalized_key:
                return phase
        return self.test_and_learn_phases[0]
