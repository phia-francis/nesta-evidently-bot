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
