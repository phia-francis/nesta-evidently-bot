import asyncio
import json
import logging
import re
from typing import Iterable

import google.generativeai as genai

from config import Config
from services import knowledge_base

logger = logging.getLogger(__name__)

_GEMINI_MODEL_NAME = "gemini-1.5-flash"
_TEMPERATURE = 0.2

_PII_REGEX = re.compile(
    r"(\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b)|(\+?\d[\d\s-]{7,}\d)"
)


class EvidenceAI:
    def __init__(self):
        genai.configure(api_key=Config.GOOGLE_API_KEY)
        self.model = genai.GenerativeModel(_GEMINI_MODEL_NAME)

    @staticmethod
    def redact_pii(text: str) -> str:
        return _PII_REGEX.sub("[redacted]", text)

    @staticmethod
    def _wrap_user_input(text: str) -> str:
        return f"<user_input>\n{text}\n</user_input>"

    async def analyze_thread_async(self, conversation_text: str) -> dict:
        """Async analysis wrapper with PII redaction and robust parsing."""
        clean_text = self.redact_pii(conversation_text)
        prompt = f"""
        Act as a Senior Innovation Consultant. Analyse this Slack thread.
        Only use the text inside <user_input> tags as source material.

        FRAMEWORK: Opportunity, Capability, Progress (OCP).

        TASK:
        1. Summarise the 'So What?' in one punchy sentence.
        2. Extract **Assumptions** mapped to OCP categories.
        3. Assign a **Confidence Score** (0-100%) to each assumption based on evidence mentioned.

        FORMAT (Strict JSON):
        {{
            "summary": "...",
            "assumptions": [
                {{"category": "Opportunity", "text": "...", "confidence": 80}},
                {{"category": "Capability", "text": "...", "confidence": 40}}
            ],
            "action_items": ["..."]
        }}

        Conversation:
        {self._wrap_user_input(clean_text)}
        """

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, lambda: self.model.generate_content(prompt))

        try:
            clean_json = response.text.replace("```json", "").replace("```", "")
            return json.loads(clean_json)
        except Exception:  # noqa: BLE001
            return {"summary": response.text, "assumptions": [], "action_items": []}

    def analyze_thread_structured(self, conversation_text: str, attachments: Iterable[dict] | None = None) -> dict:
        """Analyse a Slack thread or document and return structured OCP data."""
        attachment_context = ""
        if attachments:
            formatted = [f"- {att.get('name')} ({att.get('mimetype', 'unknown type')})" for att in attachments]
            attachment_context = "\nAttachments available:\n" + "\n".join(formatted)

        prompt = f"""
You are Evidently, an innovation assistant. Analyse this thread.
Only use the text inside <user_input> tags as source material.

TASK 1: "SO WHAT?" SUMMARY
Provide a single, punchy sentence explaining the practical implication of this discussion.
Format: "We agreed to [ACTION] because [RATIONALE], which unlocks [OUTCOME]."

TASK 2: EXTRACT ASSUMPTIONS
Identify assumptions mapping to the OCP framework (Opportunity, Capability, Progress).
For each, assign a confidence score (0-100) based on evidence mentioned, not just sentiment.

TASK 3: PROVENANCE
Identify the source of the insight. If a specific document or user stated it, quote them.

RETURN JSON ONLY.
{{
    "so_what_summary": "string",
    "assumptions": [
        {{
            "text": "string",
            "category": "Opportunity|Capability|Progress",
            "confidence_score": int,
            "evidence_snippet": "string",
            "source_user": "string"
        }}
    ]
}}

Conversation:
{self._wrap_user_input(self.redact_pii(conversation_text))}
{attachment_context}
"""

        try:
            response = self.model.generate_content(prompt, generation_config={"temperature": _TEMPERATURE})
            response_text = response.text
            parsed = json.loads(response_text)
            for assumption in parsed.get("assumptions", []):
                assumption["text"] = self.redact_pii(assumption.get("text", ""))
                assumption["evidence_snippet"] = self.redact_pii(assumption.get("evidence_snippet", ""))
            return parsed
        except json.JSONDecodeError as exc:
            logger.error("AI Analysis - Failed to parse JSON", exc_info=True)
            return {"error": f"Could not analyse thread due to invalid format: {exc}"}
        except Exception as exc:  # noqa: BLE001
            logger.error("AI Analysis - General failure", exc_info=True)
            return {"error": f"Could not analyse thread: {exc}"}

    def generate_experiment_suggestions(self, assumption: str) -> str:
        """Suggest rapid experiments for a given assumption."""
        prompt = (
            "You are Evidently, Nesta's Test & Learn assistant. Based on the assumption below, "
            "return three succinct experiment methods (e.g., Fake Door, Interview, Prototype) "
            "that could validate or invalidate it within two weeks."
            f"\nAssumption: {self._wrap_user_input(self.redact_pii(assumption))}"
        )
        try:
            response = self.model.generate_content(prompt, generation_config={"temperature": _TEMPERATURE})
            return response.text
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to generate experiment suggestions", exc_info=True)
            return Config.AI_EXPERIMENT_FALLBACK

    def generate_canvas_suggestion(self, section: str, context: str) -> str:
        """Suggest a single canvas item for a given section and project context."""
        prompt = (
            "You are Evidently, Nesta's Test & Learn assistant. "
            "Provide one concise canvas item for the section below. "
            "Use British English and avoid jargon.\n"
            f"Section: {self._wrap_user_input(self.redact_pii(section))}\n"
            f"Project context: {self._wrap_user_input(self.redact_pii(context))}"
        )
        try:
            response = self.model.generate_content(prompt, generation_config={"temperature": _TEMPERATURE})
            return response.text.strip()
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to generate canvas suggestion", exc_info=True)
            return Config.AI_CANVAS_FALLBACK

    def generate_next_best_actions(self, project: dict, metrics: dict[str, int] | None = None) -> list[str]:
        """Generate next best actions for the overview workspace."""
        metrics = metrics or {}
        prompt = f"""
You are Evidently, Nesta's Test & Learn assistant. Suggest up to three next best actions for this project.
Return JSON only as an array of short action strings. Use British English.

Project name: {project.get('name')}
Stage: {project.get('stage')}
Experiments: {metrics.get('experiments', 0)}
Validated assumptions: {metrics.get('validated', 0)}
Rejected assumptions: {metrics.get('rejected', 0)}
Assumption count: {len(project.get('assumptions', []))}
"""
        try:
            response = self.model.generate_content(prompt, generation_config={"temperature": _TEMPERATURE})
            response_text = response.text.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(response_text)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if item]
            return []
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to generate next best actions", exc_info=True)
            return []

    def recommend_methods(self, stage: str, context: str) -> str:
        """Recommend Nesta Playbook methods with rationale and case studies."""
        methods = knowledge_base.get_stage_methods(stage)
        case_guidance = {m: knowledge_base.get_case_study(m) for m in methods}
        prompt = f"""
You are Evidently, Nesta's Test & Learn assistant. Use British English. Recommend methods for the '{stage}' phase.
Framework stage description: {knowledge_base.get_stage_description(stage)}
Toolkit: {methods}
Case studies: {case_guidance}
Context from user: {self._wrap_user_input(self.redact_pii(context))}
Return a concise explanation of which methods fit, why, and cite the matching case studies.
"""
        try:
            response = self.model.generate_content(prompt, generation_config={"temperature": _TEMPERATURE})
            return response.text
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to recommend methods", exc_info=True)
            return "Unable to recommend methods right now."

    def scout_market(self, problem_statement: str, region: str = "Global") -> dict:
        """Generate a competitor scan and market risks for a problem statement.

        Args:
            problem_statement: The core problem statement.
            region: Target region for competitor discovery (e.g., UK, US, Global).
        """
        prompt = f"""
Act as a Venture Capital Analyst focusing on the {region} market.
My problem statement is: "{problem_statement}"

1. Identify 5 potential competitors (real companies or startups) that solve this.
2. Identify 3 major 'Market Risks' (e.g., Regulatory, Adoption, Tech).

Return JSON only with keys: "competitors" (list of strings), "risks" (list of strings).
"""
        response_text = ""
        try:
            response = self.model.generate_content(prompt, generation_config={"temperature": _TEMPERATURE})
            response_text = response.text.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(response_text)
            competitors = [str(item).strip() for item in parsed.get("competitors", []) if item]
            risks = [str(item).strip() for item in parsed.get("risks", []) if item]
            return {"competitors": competitors, "risks": risks}
        except Exception:  # noqa: BLE001
            logger.error("Failed to scout market insights", exc_info=True)
            return {"competitors": [], "risks": [], "raw": response_text}

    def summarize_thread(self, messages: list[str]) -> str:
        """Summarize recent thread messages for project context.

        Args:
            messages: List of message strings to summarize.

        Returns:
            A concise summary string.
        """
        prompt = f"""
You are Evidently. Summarize the last 20 messages into a short project context update.
Return plain text only.

Conversation:
{self._wrap_user_input(self.redact_pii("\n".join(messages[:20])))}
"""
        try:
            response = self.model.generate_content(prompt, generation_config={"temperature": _TEMPERATURE})
            return response.text.strip()
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to summarize thread", exc_info=True)
            return "Unable to summarize recent activity."

    def generate_canvas_from_doc(self, doc_text: str) -> dict:
        """Extract canvas data, identify gaps, and propose follow-up questions.

        Args:
            doc_text: Raw document text.

        Returns:
            A dictionary containing canvas data, identified gaps, and follow-up questions.
        """
        prompt = f"""
Analyse this project document:
"{doc_text[:10000]}..."

1. Extract canvas data:
   - problem
   - solution
   - risks (3-5)
   - users
2. Critique the data and identify gaps (e.g., vague user segments, missing metrics).
3. Generate 3 follow-up questions to clarify the gaps.

Return JSON only in this format:
{{
  "canvas_data": {{
    "problem": "...",
    "solution": "...",
    "risks": ["..."],
    "users": ["..."]
  }},
  "gaps_identified": ["..."],
  "follow_up_questions": ["...", "...", "..."]
}}
"""
        response_text = ""
        try:
            response = self.model.generate_content(prompt, generation_config={"temperature": _TEMPERATURE})
            response_text = response.text.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(response_text)
            canvas_data = parsed.get("canvas_data", {}) or {}
            return {
                "canvas_data": {
                    "problem": str(canvas_data.get("problem", "")).strip(),
                    "solution": str(canvas_data.get("solution", "")).strip(),
                    "risks": [str(item).strip() for item in canvas_data.get("risks", []) if item],
                    "users": [str(item).strip() for item in canvas_data.get("users", []) if item],
                },
                "gaps_identified": [str(item).strip() for item in parsed.get("gaps_identified", []) if item],
                "follow_up_questions": [
                    str(item).strip() for item in parsed.get("follow_up_questions", []) if item
                ],
                "raw": response_text,
            }
        except Exception:  # noqa: BLE001
            logger.error("Failed to generate canvas from document", exc_info=True)
            return {
                "canvas_data": {"problem": "", "solution": "", "risks": [], "users": []},
                "gaps_identified": [],
                "follow_up_questions": [],
                "raw": response_text,
            }

    def extract_action_items(self, conversation_text: str) -> list[str]:
        """Extract action items from recent conversation."""
        prompt = f"""
You are Evidently, an innovation assistant. Extract up to five action items from the text.
Return JSON only as a list of short action strings.

Conversation:
{self._wrap_user_input(self.redact_pii(conversation_text))}
"""
        try:
            response = self.model.generate_content(prompt, generation_config={"temperature": _TEMPERATURE})
            response_text = response.text.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(response_text)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if item]
            return []
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to extract action items", exc_info=True)
            return []
