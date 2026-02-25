import json
import random
from pathlib import Path

FULL_5_PILLAR_FRAMEWORK = {
    "1. VALUE": {
        "definition": "How does this intervention move the needle on the 2030 Mission Goal?",
        "sub_categories": {
            "Needs & Contribution": {
                "tags": [],  # universal — always shown
                "questions": [
                    "Contribution: How does this directly impact the 2030 Mission Goal?",
                    "Target Beneficiary: Are we reaching the target demographic defined in the AoF?",
                    "Evidence Gap: Does this fill a critical gap in our Theory of Change?",
                ],
            }
        },
    },
    "2. GROWTH": {
        "definition": "What are the routes to adoption and scaling?",
        "sub_categories": {
            "Routes to Scale": {
                "tags": [],
                "questions": [
                    "Scaling Mode: Which Nesta mode — Influencing, Enabling, or Delivering?",
                    "Adoption Levers: What is the specific lever? (e.g., legislative change, behavioural nudge)",
                    "Replicability: Can this work in a different context without significant reinvention?",
                ],
            }
        },
    },
    "3. SUSTAINABILITY": {
        "definition": "How does this integrate into the wider system long-term?",
        "sub_categories": {
            "System Integration": {
                "tags": ["policy", "service"],
                "questions": [
                    "System Ownership: Who owns this after Nesta steps away?",
                    "Cost-Benefit: Does the intervention save money for the system owner?",
                    "Exit Strategy: Is sustainability based on commercial revenue or public commissioning?",
                ],
            },
            "Commercial Revenue": {
                "tags": ["commercial"],
                "questions": [
                    "Revenue Model: What is the primary revenue mechanism?",
                    "Unit Economics: Are the margins viable at scale?",
                    "Market Size: Is the addressable market large enough to sustain the model?",
                ],
            },
            "Intellectual Property (IP)": {
                "tags": ["product", "digital"],
                "questions": [
                    "New IP: Is there potential to create new IP? How will you protect it?",
                    "Existing IP: What existing IP are you exploiting?",
                    "Licensing: Can licensing create additional value or protection?",
                ],
            },
        },
    },
    "4. IMPACT": {
        "definition": "What are the unintended consequences and equity impacts?",
        "sub_categories": {
            "Equity & Risk": {
                "tags": [],
                "questions": [
                    "Equity Audit: Does this unintentionally widen inequalities?",
                    "Displacement: Does success here negatively impact another part of the system?",
                    "Data Integrity: Can we capture rigorous impact data satisfying Mission Progress Indicators?",
                ],
            }
        },
    },
    "5. FEASIBILITY": {
        "definition": "Do we have the internal and external capabilities to execute?",
        "sub_categories": {
            "Capabilities & Timing": {
                "tags": [],
                "questions": [
                    "Partnership Fit: Do we have the right policy stakeholders engaged?",
                    "Internal Capability: Does this require venture building or Discovery research skills?",
                    "Political Timing: Is the external policy environment receptive?",
                ],
            },
            "R&D & Design": {
                "tags": ["product", "digital", "data"],
                "questions": [
                    "Design: What prototyping/testing capabilities exist? How are users involved?",
                    "Technology: How will technical challenges be solved?",
                ],
            },
        },
    },
}


class PlaybookService:
    """Maps assumptions to methods and provides educational content for the 5-Pillar framework."""

    def __init__(self):
        self.methods = self._load_methods()
        self.roadmap_horizons = [
            {"key": "now", "label": "NOW (Validation)", "description": "Validate the riskiest assumptions and proof points."},
            {"key": "next", "label": "NEXT (Growth)", "description": "Prove scalable channels and sustainable growth."},
            {"key": "later", "label": "LATER (System)", "description": "Embed the solution into the wider system."},
        ]
        self.test_and_learn_phases = [
            {"key": "define", "label": "DEFINE", "title": "Set direction.", "activities": ["Map stakeholder needs", "Review existing evidence", "Define target outcome"]},
            {"key": "shape", "label": "SHAPE SYSTEMS", "title": "Enable the conditions.", "activities": ["Identify blockers", "Secure permissions", "Remove bureaucratic hurdles"]},
            {"key": "develop", "label": "DEVELOP", "title": "Create solutions.", "activities": ["Generate solution ideas", "Low-fidelity prototyping", "Draft policy outlines"]},
            {"key": "test", "label": "TEST & LEARN", "title": "Experiment and learn fast.", "activities": ["Execute rapid experiments", "Wizard of Oz tests", "Analyse feedback"]},
            {"key": "scale", "label": "SCALE", "title": "Embed and expand.", "activities": ["Codify knowledge", "Integrate into BAU", "Expand to new markets"]},
        ]

    def _load_methods(self) -> dict:
        methods_path = Path(__file__).with_name("playbook_methods.json")
        with methods_path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def get_recommendations(self, category: str) -> list:
        return [
            {**method_data, "id": method_id}
            for method_id, method_data in self.methods.items()
            if category in method_data["best_for"]
        ]

    def get_method_details(self, method_id: str) -> dict | None:
        return self.methods.get(method_id)

    def get_random_tip(self) -> str:
        tips = [
            "Fall in love with the problem, not the solution.",
            "Evidence beats opinion. Data beats arguments.",
            "Test your riskiest assumption first.",
            "Fail fast, learn faster.",
        ]
        return random.choice(tips)

    def get_5_pillar_framework(self) -> dict[str, dict[str, object]]:
        return FULL_5_PILLAR_FRAMEWORK

    def get_roadmap_horizons(self) -> list[dict[str, str]]:
        return self.roadmap_horizons

    def get_test_and_learn_phases(self) -> list[dict[str, object]]:
        return self.test_and_learn_phases

    def get_phase_details(self, phase_key: str) -> dict[str, object]:
        normalised_key = (phase_key or "").strip().lower()
        for phase in self.test_and_learn_phases:
            if phase["key"] == normalised_key:
                return phase
        return self.test_and_learn_phases[0]
