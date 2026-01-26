import tempfile
from pathlib import Path

from constants import LOW_CONFIDENCE_ASSUMPTION_THRESHOLD
from services.ai_service import EvidenceAI
from services.db_service import DbService


class ReportService:
    def __init__(self, ai_service: EvidenceAI, db_service: DbService) -> None:
        self.ai_service = ai_service
        self.db_service = db_service

    @staticmethod
    def _confidence_label(score: int | None) -> str:
        if score is None:
            return "Unscored"
        if score >= 4:
            return "High"
        if score == 3:
            return "Medium"
        return "Low"

    def build_strategy_markdown(self, project: dict) -> str:
        assumptions = project.get("assumptions", [])
        experiments = project.get("experiments", [])

        summary_context = (
            f"Project: {project.get('name', 'Project')}\n"
            f"Mission: {project.get('mission', '')}\n"
            f"Description: {project.get('description', '')}\n"
            f"Assumptions: {[a.get('title') for a in assumptions]}\n"
            f"Experiments: {[e.get('title') for e in experiments]}"
        )
        executive_summary = self.ai_service.generate_executive_summary(project.get("name", "Project"), summary_context)

        ocp_sections: dict[str, list[str]] = {"Opportunity": [], "Capability": [], "Progress": []}
        for assumption in assumptions:
            category = assumption.get("category", "Opportunity")
            ocp_sections.setdefault(category, []).append(
                f"- {assumption.get('title', 'Untitled')} (Confidence: {self._confidence_label(assumption.get('confidence_score'))})"
            )

        horizons: dict[str, list[str]] = {"now": [], "next": [], "later": []}
        for assumption in assumptions:
            horizon = assumption.get("horizon", "now")
            horizons.setdefault(horizon, []).append(assumption.get("title", "Untitled"))

        action_plan = [f"- {exp.get('title', 'Untitled')} ({exp.get('status', 'Planning')})" for exp in experiments]

        decision_lines = []
        for assumption in assumptions:
            summary = self.db_service.get_decision_vote_summary(assumption["id"])
            if summary.get("count", 0) == 0:
                continue
            decision_lines.append(
                f"- {assumption.get('title', 'Untitled')}: Impact {summary['avg_impact']}, Uncertainty {summary['avg_uncertainty']}"
            )

        markdown = "\n".join(
            [
                "# Strategy Report",
                "",
                "## Executive Summary",
                executive_summary,
                "",
                "## OCP Health Check",
                "### Opportunity",
                "\n".join(ocp_sections.get("Opportunity") or ["- No items yet."]),
            ]
        )
        markdown += "\n\n### Capability\n" + "\n".join(ocp_sections.get("Capability") or ["- No items yet."])
        markdown += "\n\n### Progress\n" + "\n".join(ocp_sections.get("Progress") or ["- No items yet."])

        markdown += "\n\n## The Roadmap\n"
        markdown += "\n### Now\n" + "\n".join([f"- {item}" for item in horizons.get("now") or ["No items yet."]])
        markdown += "\n\n### Next\n" + "\n".join([f"- {item}" for item in horizons.get("next") or ["No items yet."]])
        markdown += "\n\n### Later\n" + "\n".join([f"- {item}" for item in horizons.get("later") or ["No items yet."]])

        markdown += "\n\n## Action Plan\n" + "\n".join(action_plan or ["- No experiments yet."])

        if decision_lines:
            markdown += "\n\n## Recent Decisions\n" + "\n".join(decision_lines)

        return markdown

    def generate_strategy_doc(self, project: dict) -> Path:
        markdown = self.build_strategy_markdown(project)
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".md")
        temp_file.write(markdown.encode("utf-8"))
        temp_file.flush()
        temp_file.close()
        return Path(temp_file.name)

    def generate_meeting_agenda(self, project_id: int) -> str:
        project = self.db_service.get_project(project_id)
        if not project:
            return "- Welcome & goals\n- Review project status\n- Agree next steps"
        flow_stage = (project.get("flow_stage") or "audit").lower()
        assumptions = project.get("assumptions", [])
        roadmap_plans = project.get("roadmap_plans", [])
        experiments = project.get("experiments", [])

        if flow_stage == "audit":
            low_confidence = [
                a
                for a in assumptions
                if (a.get("confidence_score") is not None)
                and 1 <= int(a.get("confidence_score") or 0) <= LOW_CONFIDENCE_ASSUMPTION_THRESHOLD
            ]
            sorted_items = sorted(low_confidence, key=lambda item: item.get("confidence_score") or 0)
            if not sorted_items:
                return "🚨 Focus: Validation. No low-confidence assumptions (score 1-2) captured yet."
            agenda_lines = [
                f"- {item.get('title', 'Untitled')} (Confidence {item.get('confidence_score')})"
                for item in sorted_items
            ]
            return "🚨 Focus: Validation. Review these low-confidence assumptions:\n" + "\n".join(agenda_lines)

        if flow_stage == "plan":
            now_items = [
                assumption.get("title", "Untitled")
                for assumption in assumptions
                if (assumption.get("horizon") or "").lower() == "now"
                or (assumption.get("lane") or "").lower() == "now"
            ]
            if not now_items:
                now_plans = [
                    plan.get("plan_now", "").strip()
                    for plan in roadmap_plans
                    if plan.get("plan_now")
                ]
                now_items = [item for item in now_plans if item]
            if not now_items:
                return "🗺️ Focus: Prioritization. No NOW horizon items defined yet."
            agenda_lines = [f"- {item}" for item in now_items]
            return "🗺️ Focus: Prioritization. Review NOW horizon items:\n" + "\n".join(agenda_lines)

        live_experiments = [
            f"- {experiment.get('title', 'Untitled')} (Status: {experiment.get('status', 'Planning')})"
            for experiment in experiments
        ]
        if not live_experiments:
            return "🧪 Focus: Results. No live experiments logged yet."
        return "🧪 Focus: Results. Review live experiments:\n" + "\n".join(live_experiments)
