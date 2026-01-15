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
    def _strip_code_fences(text: str) -> str:
        return re.sub(r"```(?:json)?", "", text).replace("```", "").strip()

    @staticmethod
    def _extract_json_fragment(text: str) -> str:
        start_candidates = [idx for idx in (text.find("{"), text.find("[")) if idx != -1]
        if not start_candidates:
            return text
        start = min(start_candidates)
        end = max(text.rfind("}"), text.rfind("]"))
        if end <= start:
            return text[start:]
        return text[start : end + 1]

    def _parse_json_response(self, response_text: str) -> dict | list:
        cleaned = self._strip_code_fences(response_text)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            fragment = self._extract_json_fragment(cleaned)
            return json.loads(fragment)

    def _parse_json_with_retry(self, response_text: str, retry_prompt: str | None = None) -> dict | list:
        try:
            return self._parse_json_response(response_text)
        except json.JSONDecodeError:
            if not retry_prompt:
                raise
            retry_response = self.model.generate_content(
                retry_prompt,
                generation_config={"temperature": _TEMPERATURE},
            )
            return self._parse_json_response(retry_response.text)

    @staticmethod
    def redact_pii(text: str) -> str:
        return _PII_REGEX.sub("[redacted]", text)

    @staticmethod
    def _wrap_user_input(text: str) -> str:
        return f"<user_input>\n{text}\n</user_input>"

    async def analyze_thread_async(self, conversation_text: str) -> dict:
        """Async analysis wrapper with PII redaction and robust parsing."""
        clean_text = self.redact_pii(conversation_text)
        playbook_context = await asyncio.to_thread(knowledge_base.get_playbook_context)
        prompt = f"""
        Act as a Senior Innovation Consultant. Analyse this Slack thread.
        Only use the text inside <user_input> tags as source material.

        FRAMEWORK: Opportunity, Capability, Progress (OCP).

        TASK:
        1. Summarise the 'So What?' in one punchy sentence.
        2. List hard decisions made.
        3. Extract assumptions mapped to OCP categories with confidence scores (0-100).
        4. Suggest relevant Test & Learn methods from the playbook.
        5. If Value Risk is detected, set suggested_method to "Fake Door Test".
           If Feasibility Risk is detected, set suggested_method to "Prototype".

        FORMAT (Strict JSON):
        {{
            "summary": "string",
            "decisions": ["string"],
            "assumptions": [
                {{"text": "string", "category": "Opportunity|Capability|Progress", "confidence": 80}}
            ],
            "recommended_methods": ["Method name"],
            "suggested_method": "string"
        }}

        Conversation:
        {self._wrap_user_input(clean_text)}

        Playbook Reference:
        {playbook_context}
        """

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, lambda: self.model.generate_content(prompt))

        try:
            parsed = self._parse_json_response(response.text)
            if isinstance(parsed, dict):
                for assumption in parsed.get("assumptions", []):
                    assumption["text"] = self.redact_pii(assumption.get("text", ""))
                    if "evidence_snippet" in assumption:
                        assumption["evidence_snippet"] = self.redact_pii(assumption.get("evidence_snippet", ""))
                    if "source_snippet" in assumption:
                        assumption["source_snippet"] = self.redact_pii(assumption.get("source_snippet", ""))
            return parsed
        except json.JSONDecodeError:
            retry_prompt = f"{prompt}\nReturn only valid JSON. No markdown or commentary."
            retry_response = await loop.run_in_executor(
                None,
                lambda: self.model.generate_content(retry_prompt),
            )
            try:
                parsed = self._parse_json_response(retry_response.text)
                if isinstance(parsed, dict):
                    for assumption in parsed.get("assumptions", []):
                        assumption["text"] = self.redact_pii(assumption.get("text", ""))
                        if "evidence_snippet" in assumption:
                            assumption["evidence_snippet"] = self.redact_pii(
                                assumption.get("evidence_snippet", "")
                            )
                        if "source_snippet" in assumption:
                            assumption["source_snippet"] = self.redact_pii(assumption.get("source_snippet", ""))
                return parsed
            except json.JSONDecodeError:
                return {"summary": response.text, "decisions": [], "assumptions": []}
        except Exception:  # noqa: BLE001
            return {"summary": response.text, "decisions": [], "assumptions": []}

    def analyze_thread_structured(self, conversation_text: str, attachments: Iterable[dict] | None = None) -> dict:
        """Analyse a Slack thread or document and return structured OCP data."""
        attachment_context = ""
        if attachments:
            formatted = [f"- {att.get('name')} ({att.get('mimetype', 'unknown type')})" for att in attachments]
            attachment_context = "\nAttachments available:\n" + "\n".join(formatted)

        playbook_context = knowledge_base.get_playbook_context()
        prompt = f"""
You are Evidently, Nesta's Test & Learn assistant. Analyse this thread.
Only use the text inside <user_input> tags as source material.

TASKS:
1. Provide a single-sentence "So What?" executive summary.
2. List hard decisions made in the conversation.
3. Extract assumptions mapped to the OCP framework (Opportunity, Capability, Progress).
   Use this logic:
   - Opportunity: end users, pain points, market size, paying customer risk.
   - Progress: solution/offer, USP, user experience, technical/legal risk.
   - Capability: champions, funding, partners/supply chain, delivery at scale.
   For each, assign a confidence score (0-100) based on evidence mentioned.
4. Suggest relevant Test & Learn methods from the playbook when helpful.
5. If Value Risk is detected, set suggested_method to "Fake Door Test".
   If Feasibility Risk is detected, set suggested_method to "Prototype".

Return JSON only in this exact shape (no Markdown, no commentary):
{{
    "summary": "string",
    "decisions": ["string"],
    "assumptions": [
        {{
            "text": "string",
            "category": "Opportunity|Capability|Progress",
            "confidence": 0
        }}
    ],
    "recommended_methods": ["Method name"],
    "suggested_method": "string"
}}

Conversation:
{self._wrap_user_input(self.redact_pii(conversation_text))}
{attachment_context}

Playbook Reference:
{playbook_context}
"""

        try:
            response = self.model.generate_content(prompt, generation_config={"temperature": _TEMPERATURE})
            parsed = self._parse_json_with_retry(
                response.text,
                retry_prompt=f"{prompt}\nReturn only valid JSON. No markdown or commentary.",
            )
            if not isinstance(parsed, dict):
                return {"error": "Could not analyse thread due to invalid JSON payload."}
            for assumption in parsed.get("assumptions", []):
                assumption["text"] = self.redact_pii(assumption.get("text", ""))
                if "evidence_snippet" in assumption:
                    assumption["evidence_snippet"] = self.redact_pii(assumption.get("evidence_snippet", ""))
                if "source_snippet" in assumption:
                    assumption["source_snippet"] = self.redact_pii(assumption.get("source_snippet", ""))
            return parsed
        except json.JSONDecodeError as exc:
            logger.error("AI Analysis - Failed to parse JSON", exc_info=True)
            return {"error": f"Could not analyse thread due to invalid format: {exc}"}
        except Exception as exc:  # noqa: BLE001
            logger.error("AI Analysis - General failure", exc_info=True)
            return {"error": f"Could not analyse thread: {exc}"}

    def suggest_experiments(self, assumption_text: str) -> list[str]:
        """Suggest three low-fidelity experiments for a given assumption."""
        if not assumption_text:
            return []
        prompt = (
            "You are Evidently, Nesta's Test & Learn assistant. "
            "Generate three specific, low-fidelity experiment ideas for the assumption below. "
            "Infer whether the assumption is Opportunity, Capability, or Progress and tailor suggestions accordingly. "
            "Return JSON only as a list of strings."
            f"\nAssumption: {self._wrap_user_input(self.redact_pii(assumption_text))}"
        )
        try:
            response = self.model.generate_content(prompt, generation_config={"temperature": _TEMPERATURE})
            parsed = self._parse_json_with_retry(
                response.text,
                retry_prompt=f"{prompt}\nReturn JSON only as a list of strings.",
            )
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
            return []
        except json.JSONDecodeError:
            logger.exception("Failed to parse Gemini response for experiment suggestions")
            return []
        except Exception:  # noqa: BLE001
            logger.exception("Failed to generate experiment suggestions")
            return []

    def generate_ocp_draft(self, context_text: str) -> dict:
        if not context_text:
            return {"error": "No context provided."}
        prompt = f"""
You are an expert Innovation Consultant. Read the attached project documents.
Extract key information to fill the "Innovation Canvas" (OCP Framework).

RETURN JSON ONLY:
{{
  "Opportunity": {{
     "User Needs": "...",
     "Market Size": "..."
  }},
  "Capability": {{
     "Resources": "...",
     "Partners": "..."
  }},
  "Progress": {{
     "Solution Description": "...",
     "Unique Selling Point": "..."
  }},
  "Insights": [
     "Based on the 'Test & Learn Playbook', I recommend a [Method Name] because [Reason]."
  ]
}}

Documents:
{self._wrap_user_input(self.redact_pii(context_text))}
"""
        try:
            response = self.model.generate_content(prompt, generation_config={"temperature": _TEMPERATURE})
            parsed = self._parse_json_with_retry(
                response.text,
                retry_prompt=f"{prompt}\nReturn only valid JSON. No markdown or commentary.",
            )
            if isinstance(parsed, dict):
                return parsed
            return {"error": "Could not generate OCP draft due to invalid JSON."}
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse OCP draft JSON", exc_info=True)
            return {"error": f"Could not generate OCP draft: {exc}"}
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to generate OCP draft", exc_info=True)
            return {"error": f"Could not generate OCP draft: {exc}"}

    def extract_ocp_from_text(self, context_text: str) -> dict:
        return self.generate_ocp_draft(context_text)

    def extract_assumptions(self, text: str) -> list[str]:
        if not text:
            return []
        system_prompt = (
            "Analyze the following text and extract a list of risky assumptions. "
            "Return the result strictly as a raw JSON list of strings (e.g. ['Assumption 1', 'Assumption 2']). "
            "Do not use Markdown formatting in the output."
        )
        try:
            clean_text = self.redact_pii(text)
            response = self.model.generate_content(f"{system_prompt}\n\n{clean_text}")
            parsed = self._parse_json_with_retry(
                response.text,
                retry_prompt=f"{system_prompt}\n\n{clean_text}\nReturn JSON only.",
            )
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
            return []
        except json.JSONDecodeError:
            logger.exception("Failed to parse Gemini response for assumptions")
            return []
        except Exception:  # noqa: BLE001
            logger.exception("Failed to extract assumptions via Gemini")
            return []

    def generate_experiment_suggestions(self, assumption: str) -> str:
        """Suggest rapid experiments for a given assumption."""
        suggestions = self.suggest_experiments(assumption)
        if suggestions:
            return "\n".join(f"- {item}" for item in suggestions)
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
            parsed = self._parse_json_with_retry(
                response.text,
                retry_prompt=f"{prompt}\nReturn JSON only as an array of strings.",
            )
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
            response_text = response.text
            parsed = self._parse_json_with_retry(
                response_text,
                retry_prompt=f"{prompt}\nReturn JSON only with keys: competitors, risks.",
            )
            if not isinstance(parsed, dict):
                raise json.JSONDecodeError("Invalid JSON payload", response_text, 0)
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
            response_text = response.text
            parsed = self._parse_json_with_retry(
                response_text,
                retry_prompt=f"{prompt}\nReturn JSON only. No markdown.",
            )
            if not isinstance(parsed, dict):
                raise json.JSONDecodeError("Invalid JSON payload", response_text, 0)
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
            parsed = self._parse_json_with_retry(
                response.text,
                retry_prompt=f"{prompt}\nReturn JSON only as a list of strings.",
            )
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if item]
            return []
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to extract action items", exc_info=True)
            return []


class AiService:
    def __init__(self) -> None:
        genai.configure(api_key=Config.GOOGLE_API_KEY)
        self.model = genai.GenerativeModel("gemini-1.5-flash")

    def extract_assumptions(self, text: str) -> list[str]:
        if not text:
            return []
        system_prompt = (
            "Analyze the following text and extract a list of risky assumptions. "
            "Return the result strictly as a raw JSON list of strings (e.g. ['Assumption 1', 'Assumption 2']). "
            "Do not use Markdown formatting in the output."
        )
        try:
            clean_text = EvidenceAI.redact_pii(text)
            response = self.model.generate_content(f"{system_prompt}\n\n{clean_text}")
            content = response.text.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(content or "[]")
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
            return []
        except json.JSONDecodeError:
            logger.exception("Failed to parse Gemini response for assumptions")
            return []
        except Exception:  # noqa: BLE001
            logger.exception("Failed to extract assumptions via Gemini")
            return []
