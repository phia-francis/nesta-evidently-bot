from types import SimpleNamespace

import google.generativeai as genai

from services.ai_service import EvidenceAI


class DummyModel:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def generate_content(self, *_args, **_kwargs):
        return SimpleNamespace(text="{}")


def _build_ai(response_text: str) -> EvidenceAI:
    class ResponseModel(DummyModel):
        def generate_content(self, *_args, **_kwargs):
            return SimpleNamespace(text=response_text)

    original_model = genai.GenerativeModel
    genai.GenerativeModel = ResponseModel  # type: ignore[assignment]
    try:
        return EvidenceAI()
    finally:
        genai.GenerativeModel = original_model  # type: ignore[assignment]


def test_analyze_thread_structured_handles_markdown_json():
    ai = _build_ai(
        "```json\n"
        '{"summary": "ok", "decisions": [], "assumptions": [], "recommended_methods": [], "suggested_method": ""}'
        "\n```"
    )
    result = ai.analyze_thread_structured("hello world")
    assert result["summary"] == "ok"


def test_analyze_thread_structured_handles_bad_json():
    ai = _build_ai("```json\n{bad}\n```")
    result = ai.analyze_thread_structured("hello world")
    assert "error" in result
