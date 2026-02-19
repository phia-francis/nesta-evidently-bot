import json
import random
from pathlib import Path


FULL_5_PILLAR_FRAMEWORK = {
    "1. VALUE": {
        "definition": "How does this specific intervention move the needle on the 2030 Mission Goal?",
        "sub_categories": {
            "Needs & Contribution": [
                "Contribution: How does this intervention directly impact the 2030 Mission Goal (e.g., halving obesity, reducing carbon emissions)?",
                "Target Beneficiary: Are we reaching the specific target demographic defined in the Area of Focus (AoF)?",
                "Evidence Gap: Does this fill a critical evidence gap in our Theory of Change, or are we replicating existing knowledge?"
            ]
        }
    },
    "2. GROWTH": {
        "definition": "What are the routes to adoption and scaling?",
        "sub_categories": {
            "Routes to Scale": [
                "Scaling Mode: Which Nesta scaling mode does this fit: Influencing, Enabling, or Delivering?",
                "Adoption Levers: What is the specific lever for adoption? (e.g., legislative change, supply chain incentive, behavioral nudge)",
                "Replicability: Can this model work in a different local authority or context without significant reinvention?"
            ]
        }
    },
    "3. SUSTAINABILITY": {
        "definition": "How does this integrate into the wider system long-term?",
        "sub_categories": {
            "System Integration": [
                "System Ownership: Who owns this problem after Nesta steps away? (e.g., Local Authority, NHS, private market)",
                "Cost-Benefit: Does the intervention save money for the system owner to justify long-term funding?",
                "Exit Strategy: Is the sustainability plan based on commercial revenue (Venture) or public commissioning (Program)?"
            ]
        }
    },
    "4. IMPACT": {
        "definition": "What are the unintended consequences and equity impacts?",
        "sub_categories": {
            "Equity & Risk": [
                "Equity Audit: Does this intervention unintentionally widen inequalities?",
                "Displacement: Does success here negatively impact another part of the system?",
                "Data Integrity: Can we capture rigorous impact data in a way that satisfies our Mission Progress Indicators?"
            ]
        }
    },
    "5. FEASIBILITY": {
        "definition": "Do we have the internal and external capabilities to execute?",
        "sub_categories": {
            "Capabilities & Timing": [
                "Partnership Fit: Do we have the right 'Gold Policy Stakeholders' engaged to unblock barriers?",
                "Internal Capability: Does this require Mission Studio venture building skills or Discovery research skills?",
                "Political Timing: Is the external policy environment currently receptive to this change?"
            ]
        }
    }
}


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
                "label": "NOW (Validation)",
                "description": "Validate the riskiest assumptions and proof points.",
            },
            {
                "key": "next",
                "label": "NEXT (Growth)",
                "description": "Prove scalable channels and sustainable growth.",
            },
            {
                "key": "later",
                "label": "LATER (System)",
                "description": "Embed the solution into the wider system.",
            },
        ]
        self.test_and_learn_phases = [
            {
                "key": "define",
                "label": "DEFINE",
                "title": "Set direction.",
                "activities": ["Map stakeholder needs", "Review existing evidence", "Define target outcome"],
            },
            {
                "key": "shape",
                "label": "SHAPE SYSTEMS",
                "title": "Enable the conditions.",
                "activities": ["Identify blockers", "Secure permissions", "Remove bureaucratic hurdles"],
            },
            {
                "key": "develop",
                "label": "DEVELOP",
                "title": "Create solutions.",
                "activities": ["Generate solution ideas", "Low-fidelity prototyping", "Draft policy outlines"],
            },
            {
                "key": "test",
                "label": "TEST & LEARN",
                "title": "Experiment and learn fast.",
                "activities": ["Execute rapid experiments", "Wizard of Oz tests", "Analyze feedback"],
            },
            {
                "key": "scale",
                "label": "SCALE",
                "title": "Embed and expand.",
                "activities": ["Codify knowledge", "Integrate into BAU", "Expand to new markets"],
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

    def get_5_pillar_framework(self) -> dict[str, dict[str, object]]:
        return FULL_5_PILLAR_FRAMEWORK

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
