class ToolkitService:
    STAGES = {
        "DEFINE": {
            "desc": "Understand the problem and stakeholder needs.",
            "methods": ["Stakeholder Interviews", "Data Mining", "User Journey Mapping"],
            "case_study": "See how 'Council X' defined fuel poverty metrics.",
        },
        "DEVELOP": {
            "desc": "Generate solutions and draft policy outlines.",
            "methods": ["Crazy 8s", "Rapid Prototyping", "Policy Drafting"],
            "case_study": "Drafting the AI Safety Bill: A Retrospective.",
        },
        "REFINE": {
            "desc": "Test critical assumptions via rapid feedback.",
            "methods": ["Fake Door Test", "Concierge MVP", "Usability Testing"],
            "case_study": "Refining the NHS App interface.",
        },
        "EVALUATE": {
            "desc": "Understand what works to achieve outcomes.",
            "methods": ["A/B Testing", "RCT (Randomized Control Trial)", "Impact Analysis"],
            "case_study": "Evaluating the sugar tax impact.",
        },
        "DIFFUSE": {
            "desc": "Scale proven solutions.",
            "methods": ["Playbook Creation", "Train the Trainer", "Open Sourcing"],
            "case_study": "Scaling the GovernUp platform.",
        },
    }

    def get_stage_info(self, stage: str) -> dict:
        return self.STAGES.get(stage.upper(), self.STAGES["DEFINE"])

    def get_question_bank(self, method_name: str) -> list[str]:
        """Returns a list of interview questions based on the method."""
        banks = {
            "User Interview": [
                "Tell me about the last time you encountered [Problem]?",
                "What was the hardest part about that experience?",
                "How do you currently solve this problem?",
                "What solutions have you tried that failed?",
            ],
            "Fake Door": [
                "What would you expect to happen after clicking this button?",
                "How much would you expect to pay for this service?",
                "On a scale of 1-10, how disappointed would you be if this didn't exist?",
            ],
            "Concept Testing": [
                "Who do you think this product is for?",
                "What is the most unclear part of this concept?",
                "Does this remind you of anything else you use?",
            ],
        }
        for key in banks:
            if key.lower() in method_name.lower():
                return banks[key]
        return banks["User Interview"]
