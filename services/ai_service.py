import asyncio
import json
import logging
import re
from typing import Iterable

import google.generativeai as genai

from config import Category, Config
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

    async def analyze_thread_async(self, conversation_text: str) -> dict:
        """Async analysis wrapper with PII redaction and robust parsing."""
        clean_text = self.redact_pii(conversation_text)
        prompt = f"""
        Act as a Senior Innovation Consultant. Analyse this Slack thread.

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
        {clean_text}
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
You are Evidently, Nesta's Test & Learn assistant. Respond in strict JSON using British English for free text.
Reference Playbook: {knowledge_base.FRAMEWORK_STAGES}
Methods Toolkit: {knowledge_base.METHODS_TOOLKIT}
Case Studies: {knowledge_base.CASE_STUDIES}
Keys: summary (string), key_decision (boolean), action_items (array of strings), emergent_assumptions (array of strings), assumptions (array of objects).
Each assumption object must include: id (stable hash or slug), text, category (one of {Category.OPPORTUNITY.value}, {Category.CAPABILITY.value}, {Category.PROGRESS.value}), confidence_score (integer 0-100), status ("active" or "stale"), provenance_source (string e.g. meeting name), source_id (string identifier), last_verified_at (ISO8601 string or null).
Conversation:
{self.redact_pii(conversation_text)}
{attachment_context}
"""

        try:
            response = self.model.generate_content(prompt, generation_config={"temperature": _TEMPERATURE})
            response_text = response.text
            parsed = json.loads(response_text)
            for assumption in parsed.get("assumptions", []):
                assumption["text"] = self.redact_pii(assumption.get("text", ""))
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
            f"\nAssumption: {assumption}"
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
            f"Section: {section}\n"
            f"Project context: {context}"
        )
        try:
            response = self.model.generate_content(prompt, generation_config={"temperature": _TEMPERATURE})
            return response.text.strip()
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to generate canvas suggestion", exc_info=True)
            return Config.AI_CANVAS_FALLBACK

    def recommend_methods(self, stage: str, context: str) -> str:
        """Recommend Nesta Playbook methods with rationale and case studies."""
        methods = knowledge_base.get_stage_methods(stage)
        case_guidance = {m: knowledge_base.get_case_study(m) for m in methods}
        prompt = f"""
You are Evidently, Nesta's Test & Learn assistant. Use British English. Recommend methods for the '{stage}' phase.
Framework stage description: {knowledge_base.get_stage_description(stage)}
Toolkit: {methods}
Case studies: {case_guidance}
Context from user: {context}
Return a concise explanation of which methods fit, why, and cite the matching case studies.
"""
        try:
            response = self.model.generate_content(prompt, generation_config={"temperature": _TEMPERATURE})
            return response.text
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to recommend methods", exc_info=True)
            return "Unable to recommend methods right now."
