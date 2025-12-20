"""Embedded Nesta Test & Learn playbook knowledge."""

FRAMEWORK_STAGES = {
    "define": "Define target outcomes; understand the problem, context, and stakeholder needs.",
    "shape systems": "Spot blockers to a test-and-learn approach and remove them.",
    "develop": "Generate solutions; create early prototypes and draft policy outlines.",
    "refine": "Refine solutions through rapid feedback cycles; test critical assumptions first.",
    "evaluate": "Understand what works to achieve outcomes and scale.",
    "diffuse and scale": "Scale proven solutions; help knowledge and good practice spread.",
}

METHODS_TOOLKIT = {
    "define": [
        "System Mapping",
        "Evidence Reviews",
        "Data Analytics",
        "User Research",
        "Collective Intelligence",
    ],
    "develop": [
        "Speed Testing",
        "Policy Blueprinting",
        "Theory of Change",
        "Deliberative Methods",
    ],
    "refine": [
        "Prototyping",
        "Online Trials",
        "Nimble Trials",
        "Implementation Evaluation",
    ],
    "evaluate": [
        "RCTs",
        "Quasi-experimental designs",
        "Theory-based evaluation",
        "Value for Money methods",
    ],
    "diffuse and scale": [
        "Scale-up evaluation",
        "Franchises/Licenses",
    ],
    "shape systems": [
        "Regulatory Sandboxes",
        "Challenge Prizes",
        "Funding Mechanisms",
    ],
}

CASE_STUDIES = {
    "Data Analytics": "York Ward Profile – linked administrative datasets to target early years support.",
    "System Mapping": "Homerton Hospital – mapped patient discharge delays to find leverage points.",
    "Speed Testing": "Interim Boilers – rapidly tested and ruled out a boiler rental service.",
    "Prototyping": "Visit a Heat Pump – refined a service connecting curious homeowners with heat pump owners.",
    "Nimble Trials": "National Tutoring Programme – tested pupil engagement strategies via rapid A/B tests.",
    "Challenge Prizes": "Longitude Prize – incentivised new antimicrobial resistance tests.",
    "Online Trials": "National Tutoring Programme – tested pupil engagement strategies via rapid A/B tests.",
    "Implementation Evaluation": "Visit a Heat Pump – refined through iterative prototyping and measurement.",
    "RCTs": "National Tutoring Programme – applied randomised comparisons to understand impact.",
    "Regulatory Sandboxes": "Longitude Prize – used challenge-driven experimentation to unlock innovation.",
}


def get_stage_methods(stage: str) -> list:
    return METHODS_TOOLKIT.get(stage.lower(), [])


def get_stage_description(stage: str) -> str:
    return FRAMEWORK_STAGES.get(stage.lower(), "")


def get_case_study(method: str) -> str:
    return CASE_STUDIES.get(method, "")
