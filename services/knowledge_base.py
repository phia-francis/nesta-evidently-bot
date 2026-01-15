"""Embedded Nesta Test & Learn playbook knowledge."""

FRAMEWORK_STAGES = {
    "define": {
        "description": "Define target outcomes; understand the problem, context, and stakeholder needs.",
        "methods": [
            "System mapping",
            "Evidence reviews",
            "Data analytics",
            "User research",
            "Collective intelligence",
        ],
        "raw": (
            "DEFINE: Define target outcomes; understand the problem, context, and stakeholder needs. "
            "(Methods: System mapping, Evidence reviews, Data analytics, User research, Collective intelligence)."
        ),
    },
    "shape systems": {
        "description": "Spot blockers to a test-and-learn approach and remove them.",
        "methods": [
            "Regulatory sandboxes",
            "Challenge prizes",
            "Funding mechanisms",
        ],
        "raw": (
            "SHAPE SYSTEMS: Spot blockers to a test-and-learn approach and remove them. "
            "(Methods: Regulatory sandboxes, Challenge prizes, Funding mechanisms)."
        ),
    },
    "develop": {
        "description": "Generate solutions; create early prototypes and draft policy outlines.",
        "methods": [
            "Speed testing",
            "Policy blueprinting",
            "Theory of change",
            "Deliberative methods",
        ],
        "raw": (
            "DEVELOP: Generate solutions; create early prototypes and draft policy outlines. "
            "(Methods: Speed testing, Policy blueprinting, Theory of change, Deliberative methods)."
        ),
    },
    "refine": {
        "description": "Refine solutions through rapid feedback cycles; test critical assumptions first.",
        "methods": [
            "Prototyping",
            "Online trials",
            "Nimble trials",
            "Implementation evaluation",
        ],
        "raw": (
            "REFINE: Refine solutions through rapid feedback cycles; test critical assumptions first. "
            "(Methods: Prototyping, Online trials, Nimble trials, Implementation evaluation)."
        ),
    },
    "evaluate": {
        "description": "Understand what works to achieve outcomes and scale.",
        "methods": [
            "RCTs",
            "Quasi-experimental designs",
            "Theory-based evaluation",
            "Value for Money methods",
        ],
        "raw": (
            "EVALUATE: Understand what works to achieve outcomes and scale. "
            "(Methods: RCTs, Quasi-experimental designs, Theory-based evaluation, Value for Money methods)."
        ),
    },
    "diffuse and scale": {
        "description": "Scale proven solutions; help knowledge and good practice spread.",
        "methods": [
            "Scale-up evaluation",
            "Franchises/Licenses",
        ],
        "raw": (
            "DIFFUSE AND SCALE: Scale proven solutions; help knowledge and good practice spread. "
            "(Methods: Scale-up evaluation, Franchises/Licenses)."
        ),
    },
}

METHOD_DETAILS = {
    "data analytics": {
        "description": "Using administrative datasets to target support.",
        "case_study": (
            '"York Ward Profile" – linked 10 data sources to target early years support.'
        ),
    },
    "system mapping": {
        "description": "Visualising complex interconnections.",
        "case_study": (
            '"Homerton Hospital" – mapped patient discharge delays to identify leverage points '
            "like pharmacy cut-off times."
        ),
    },
    "theory of change": {
        "description": (
            "Articulating causal links to identify critical assumptions. Best developed through "
            "multidisciplinary workshops."
        ),
        "case_study": "",
    },
    "policy blueprinting": {"description": "", "case_study": ""},
    "deliberative methods": {"description": "", "case_study": ""},
    "speed testing": {
        "description": (
            "Rapidly testing new ideas with real-world feedback to spot, refine, or discount them."
        ),
        "case_study": (
            '"Interim Boilers" – Nesta tested providing temporary boilers; findings on high rental costs '
            "led to ruling it out quickly."
        ),
    },
    "iterative prototyping": {
        "description": "Developing a minimum viable version to test.",
        "case_study": (
            '"Visit a Heat Pump" – started with simple mockups for homeowners; evolved into a platform '
            "with 400+ hosts after 200+ iterations."
        ),
    },
    "prototyping": {
        "description": "Developing a minimum viable version to test.",
        "case_study": (
            '"Visit a Heat Pump" – started with simple mockups for homeowners; evolved into a platform '
            "with 400+ hosts after 200+ iterations."
        ),
    },
    "online experiments": {
        "description": "Testing in tailored digital environments.",
        "case_study": (
            '"AI Chatbots" – BIT tested public engagement with chatbots; found they increased acceptance '
            "but didn't always improve task speed."
        ),
    },
    "online trials": {
        "description": "Testing in tailored digital environments.",
        "case_study": (
            '"AI Chatbots" – BIT tested public engagement with chatbots; found they increased acceptance '
            "but didn't always improve task speed."
        ),
    },
    "nimble trials": {
        "description": "Quick, cheap RCTs conducted within weeks.",
        "case_study": (
            '"National Tutoring Programme" – tested pupil engagement strategies; a quick survey increased '
            "attendance by 4.2 percentage points."
        ),
    },
    "implementation evaluation": {"description": "", "case_study": ""},
    "rcts": {"description": "", "case_study": ""},
    "quasi-experimental designs": {"description": "", "case_study": ""},
    "theory-based evaluation": {"description": "", "case_study": ""},
    "value for money methods": {"description": "", "case_study": ""},
    "scale-up evaluation": {"description": "", "case_study": ""},
    "franchises/licenses": {"description": "", "case_study": ""},
    "challenge prizes": {
        "description": "Competitions that reward whoever solves a problem first.",
        "case_study": (
            '"Longitude Prize" – incentivised rapid antimicrobial resistance tests; winner Sysmex Astrego '
            "developed a 45-minute test."
        ),
    },
    "regulatory sandboxes": {
        "description": (
            "Temporary waivers to regulations to allow testing. Used to test innovations under live "
            "conditions safely."
        ),
        "case_study": "",
    },
    "evidence reviews": {"description": "", "case_study": ""},
    "user research": {"description": "", "case_study": ""},
    "collective intelligence": {"description": "", "case_study": ""},
    "funding mechanisms": {"description": "", "case_study": ""},
}


def _normalise(text: str) -> str:
    return text.strip().lower()


def get_stage_methods(stage: str) -> list:
    return FRAMEWORK_STAGES.get(stage.lower(), {}).get("methods", [])


def get_stage_description(stage: str) -> str:
    return FRAMEWORK_STAGES.get(stage.lower(), {}).get("description", "")


def get_methods_for_stage(stage: str) -> list:
    return get_stage_methods(stage)


def get_method_details(method_name: str) -> dict:
    details = METHOD_DETAILS.get(_normalise(method_name), {})
    return {
        "description": details.get("description", ""),
        "case_study": details.get("case_study", ""),
    }


def get_case_study(method: str) -> str:
    return get_method_details(method).get("case_study", "")


def get_playbook_context() -> str:
    stage_lines = [info["raw"] for info in FRAMEWORK_STAGES.values()]
    method_lines = [
        "Data Analytics: Using administrative datasets to target support. Case Study: "
        '"York Ward Profile" – linked 10 data sources to target early years support.',
        "System Mapping: Visualising complex interconnections. Case Study: "
        '"Homerton Hospital" – mapped patient discharge delays to identify leverage points like pharmacy cut-off times.',
        "Theory of Change: Articulating causal links to identify critical assumptions. "
        "Best developed through multidisciplinary workshops.",
        "Speed Testing: Rapidly testing new ideas with real-world feedback to spot, refine, or discount them. "
        'Case Study: "Interim Boilers" – Nesta tested providing temporary boilers; findings on high rental costs '
        "led to ruling it out quickly.",
        "Iterative Prototyping: Developing a minimum viable version to test. Case Study: "
        '"Visit a Heat Pump" – started with simple mockups for homeowners; evolved into a platform with 400+ hosts '
        "after 200+ iterations.",
        "Online Experiments: Testing in tailored digital environments. Case Study: "
        '"AI Chatbots" – BIT tested public engagement with chatbots; found they increased acceptance but didn\'t '
        "always improve task speed.",
        "Nimble Trials: Quick, cheap RCTs conducted within weeks. Case Study: "
        '"National Tutoring Programme" – tested pupil engagement strategies; a quick survey increased attendance '
        "by 4.2 percentage points.",
        "Challenge Prizes: Competitions that reward whoever solves a problem first. Case Study: "
        '"Longitude Prize" – incentivised rapid antimicrobial resistance tests; winner Sysmex Astrego developed a '
        "45-minute test.",
        "Regulatory Sandboxes: Temporary waivers to regulations to allow testing. Used to test innovations under "
        "live conditions safely.",
    ]
    return "\n".join(stage_lines + ["", "DETAILED METHOD DEFINITIONS:"] + method_lines)
