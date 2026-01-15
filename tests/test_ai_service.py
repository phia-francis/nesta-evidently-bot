from types import SimpleNamespace

import pytest

import google.generativeai as genai

from services.ai_service import EvidenceAI


class DummyModel:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def generate_content(self, *_args, **_kwargs):
        return SimpleNamespace(text="{}")


def _build_ai(*response_texts: str) -> EvidenceAI:
    texts = list(response_texts)
    if not texts:
        texts = ["{}"]

    class ResponseModel(DummyModel):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()
            self._index = 0

        def generate_content(self, *_args, **_kwargs):
            text = texts[min(self._index, len(texts) - 1)]
            self._index += 1
            return SimpleNamespace(text=text)

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


def test_analyze_thread_structured_retries_and_redacts_snippets():
    ai = _build_ai(
        "```json\n{bad}\n```",
        "```json\n"
        '{"summary": "ok", "decisions": [], "assumptions": [{"text": "email a@b.com", '
        '"evidence_snippet": "email a@b.com"}], "recommended_methods": [], "suggested_method": ""}'
        "\n```",
    )
    result = ai.analyze_thread_structured("hello world")
    assert result["summary"] == "ok"
    assert result["assumptions"][0]["text"] == "email [redacted]"
    assert result["assumptions"][0]["evidence_snippet"] == "email [redacted]"


@pytest.mark.asyncio
async def test_analyze_thread_async_redacts_snippets():
    ai = _build_ai(
        "```json\n"
        '{"summary": "ok", "decisions": [], "assumptions": [{"text": "call +15551234567", '
        '"source_snippet": "call +15551234567"}]}'
        "\n```"
    )
    result = await ai.analyze_thread_async("hello world")
    assert result["assumptions"][0]["text"] == "call [redacted]"
    assert result["assumptions"][0]["source_snippet"] == "call [redacted]"
