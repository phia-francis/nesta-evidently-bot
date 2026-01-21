import json
import random
from pathlib import Path


FULL_5_PILLAR_FRAMEWORK = {
    "1. VALUE": {
        "definition": "What needs to be true about user and stakeholder value?",
        "sub_categories": {
            "Needs": {
                "questions": [
                    "• User Needs: Who is the end user? What needs does your innovation meet?",
                    "• Pain Points: What difficulty or frustration does it overcome?",
                    "• Customer: Who will pay? What is their incentive?",
                ],
                "roadmap_context": "What do we need to learn about User Needs?",
            },
            "Approach": {
                "questions": [
                    "• Description: What is the product, service, or process?",
                    "• User Benefits: How does it meet the needs? What value does it create?",
                    "• USP: What makes it stand out from the competition?",
                ],
                "roadmap_context": "What do we need to learn about our Approach?",
            },
        },
    },
    "2. GROWTH": {
        "definition": "What needs to be true about adoption and scaling?",
        "sub_categories": {
            "Market": {
                "questions": [
                    "• Size & Trends: What is the target market size?",
                    "• Barriers: What obstacles make it hard to enter?",
                    "• Competition: What competes with you?",
                ],
                "roadmap_context": "What do we need to learn about the Market?",
            },
            "Experience": {
                "questions": [
                    "• Discovery: Sales/marketing strategy?",
                    "• Transaction: Pricing & payment?",
                    "• User Experience: Usage over time?",
                ],
                "roadmap_context": "What do we need to learn about Experience?",
            },
        },
    },
    "3. SUSTAINABILITY": {
        "definition": "What needs to be true about funding and sustainability?",
        "sub_categories": {
            "Finance": {
                "questions": [
                    "• Revenue & Cost?",
                    "• Funding?",
                    "• Cashflow?",
                ],
                "roadmap_context": "What do we need to learn about Finance?",
            },
            "IP": {
                "questions": [
                    "• New IP?",
                    "• Existing IP?",
                    "• Licensing?",
                ],
                "roadmap_context": "What do we need to learn about IP?",
            },
        },
    },
    "4. IMPACT": {
        "definition": "What needs to be true about intended outcomes?",
        "sub_categories": {
            "Risk": {
                "questions": [
                    "• Identify Risks?",
                    "• Assess Impact?",
                    "• Mitigate?",
                    "• Performance Metrics?",
                ],
                "roadmap_context": "What do we need to learn about Risks?",
            },
            "Rules": {
                "questions": [
                    "• Freedom to Operate?",
                    "• Legislation?",
                    "• Standards?",
                ],
                "roadmap_context": "What do we need to learn about Rules?",
            },
            "Wider Impact": {
                "questions": [
                    "• Economic?",
                    "• Social?",
                    "• Environmental?",
                ],
                "roadmap_context": "What do we need to learn about Wider Impact?",
            },
        },
    },
    "5. FEASIBILITY": {
        "definition": "What needs to be true about implementation?",
        "sub_categories": {
            "R&D": {
                "questions": [
                    "• Idea Generation?",
                    "• Prototyping Capabilities?",
                    "• Technical Challenges?",
                ],
                "roadmap_context": "What do we need to learn about R&D?",
            },
            "Operations": {
                "questions": [
                    "• Skills/People?",
                    "• Equipment?",
                    "• Outsourcing?",
                    "• Stakeholders?",
                ],
                "roadmap_context": "What do we need to learn about Operations?",
            },
            "Leadership": {
                "questions": [
                    "• Champions?",
                    "• Management Expertise?",
                    "• Strategy?",
                ],
                "roadmap_context": "What do we need to learn about Leadership?",
            },
        },
    },
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
