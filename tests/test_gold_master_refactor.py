"""Tests for the Gold Master Refactor — 5-Pillar Framework, Config validation,
AI service output format, home tab rendering, and modals."""

import json
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cryptography.fernet import Fernet
import google.generativeai as genai


# ---------------------------------------------------------------------------
# Task 1 — Framework data structure
# ---------------------------------------------------------------------------


class TestFrameworkStructure:
    def test_framework_has_five_pillars(self):
        from services.playbook_service import FULL_5_PILLAR_FRAMEWORK

        assert len(FULL_5_PILLAR_FRAMEWORK) == 5
        expected_keys = ["1. VALUE", "2. GROWTH", "3. SUSTAINABILITY", "4. IMPACT", "5. FEASIBILITY"]
        assert list(FULL_5_PILLAR_FRAMEWORK.keys()) == expected_keys

    def test_each_pillar_has_definition_and_sub_categories(self):
        from services.playbook_service import FULL_5_PILLAR_FRAMEWORK

        for pillar_key, pillar_data in FULL_5_PILLAR_FRAMEWORK.items():
            assert "definition" in pillar_data, f"{pillar_key} missing definition"
            assert "sub_categories" in pillar_data, f"{pillar_key} missing sub_categories"

    def test_sub_categories_are_lists_of_strings(self):
        from services.playbook_service import FULL_5_PILLAR_FRAMEWORK

        for pillar_key, pillar_data in FULL_5_PILLAR_FRAMEWORK.items():
            for sub_cat_name, sub_category_questions in pillar_data["sub_categories"].items():
                assert isinstance(sub_category_questions, list), (
                    f"{pillar_key} -> {sub_cat_name} should be a list, got {type(sub_category_questions)}"
                )
                for question in sub_category_questions:
                    assert isinstance(question, str), (
                        f"Questions in {pillar_key} -> {sub_cat_name} should be strings"
                    )

    def test_value_pillar_definition(self):
        from services.playbook_service import FULL_5_PILLAR_FRAMEWORK

        assert "2030 Mission Goal" in FULL_5_PILLAR_FRAMEWORK["1. VALUE"]["definition"]

    def test_value_pillar_sub_category(self):
        from services.playbook_service import FULL_5_PILLAR_FRAMEWORK

        sub_cats = FULL_5_PILLAR_FRAMEWORK["1. VALUE"]["sub_categories"]
        assert "Needs & Contribution" in sub_cats
        assert len(sub_cats["Needs & Contribution"]) == 3

    def test_growth_pillar_sub_category(self):
        from services.playbook_service import FULL_5_PILLAR_FRAMEWORK

        sub_cats = FULL_5_PILLAR_FRAMEWORK["2. GROWTH"]["sub_categories"]
        assert "Routes to Scale" in sub_cats
        assert len(sub_cats["Routes to Scale"]) == 3

    def test_playbook_service_returns_framework(self):
        from services.playbook_service import PlaybookService

        service = PlaybookService()
        framework = service.get_5_pillar_framework()
        assert "1. VALUE" in framework
        assert "5. FEASIBILITY" in framework


# ---------------------------------------------------------------------------
# Task 3a — Config.validate()
# ---------------------------------------------------------------------------


class TestConfigValidation:
    def test_validate_raises_without_slack_token(self):
        from config import Config

        original = Config.SLACK_BOT_TOKEN
        try:
            Config.SLACK_BOT_TOKEN = None
            with pytest.raises(ValueError, match="xoxb-"):
                Config.validate()
        finally:
            Config.SLACK_BOT_TOKEN = original

    def test_validate_raises_with_invalid_slack_token(self):
        from config import Config

        original = Config.SLACK_BOT_TOKEN
        try:
            Config.SLACK_BOT_TOKEN = "invalid-token"
            with pytest.raises(ValueError, match="xoxb-"):
                Config.validate()
        finally:
            Config.SLACK_BOT_TOKEN = original

    def test_validate_passes_with_valid_token(self):
        from config import Config

        original = Config.SLACK_BOT_TOKEN
        try:
            Config.SLACK_BOT_TOKEN = "xoxb-test-token"
            Config.validate()  # Should not raise
        finally:
            Config.SLACK_BOT_TOKEN = original

    def test_get_encryption_key_returns_fallback_in_dev(self):
        from config import get_encryption_key, _FALLBACK_ENCRYPTION_KEY

        original_env = os.environ.pop("GOOGLE_TOKEN_ENCRYPTION_KEY", None)
        original_environment = os.environ.get("ENVIRONMENT")
        try:
            os.environ.pop("ENVIRONMENT", None)
            key = get_encryption_key()
            assert key == _FALLBACK_ENCRYPTION_KEY
        finally:
            if original_env is not None:
                os.environ["GOOGLE_TOKEN_ENCRYPTION_KEY"] = original_env
            if original_environment is not None:
                os.environ["ENVIRONMENT"] = original_environment

    def test_fallback_key_is_valid_fernet(self):
        from config import _FALLBACK_ENCRYPTION_KEY

        # Should not raise — the key must be a valid Fernet key
        Fernet(_FALLBACK_ENCRYPTION_KEY)


# ---------------------------------------------------------------------------
# Task 6 — AI Service extract_structured_assumption output format
# ---------------------------------------------------------------------------


def _build_ai(*response_texts: str):
    from services.ai_service import EvidenceAI

    texts = list(response_texts) or ["{}"]

    class ResponseModel:
        def __init__(self, *_args, **_kwargs):
            self._index = 0

        def generate_content(self, *_args, **_kwargs):
            text = texts[min(self._index, len(texts) - 1)]
            self._index += 1
            return SimpleNamespace(text=text)

    original_model = genai.GenerativeModel
    genai.GenerativeModel = ResponseModel
    try:
        return EvidenceAI()
    finally:
        genai.GenerativeModel = original_model


class TestExtractStructuredAssumption:
    def test_output_has_new_field_names(self):
        response_json = json.dumps({
            "title": "Test assumption",
            "matched_category": "2. GROWTH",
            "matched_sub_category": "Routes to Scale",
            "estimated_confidence_score": 4,
        })
        ai = _build_ai(response_json)
        result = ai.extract_structured_assumption("some raw text")
        assert "matched_category" in result
        assert "matched_sub_category" in result
        assert "estimated_confidence_score" in result
        assert result["title"] == "Test assumption"
        assert result["matched_category"] == "2. GROWTH"
        assert result["matched_sub_category"] == "Routes to Scale"
        assert result["estimated_confidence_score"] == 4

    def test_empty_input_returns_error(self):
        ai = _build_ai("{}")
        result = ai.extract_structured_assumption("")
        assert "error" in result

    def test_invalid_pillar_defaults_to_value(self):
        response_json = json.dumps({
            "title": "Assumption",
            "matched_category": "INVALID",
            "matched_sub_category": "Something",
            "estimated_confidence_score": 3,
        })
        ai = _build_ai(response_json)
        result = ai.extract_structured_assumption("some text")
        assert result["matched_category"] == "1. VALUE"

    def test_confidence_clamped_to_range(self):
        response_json = json.dumps({
            "title": "Assumption",
            "matched_category": "1. VALUE",
            "matched_sub_category": "Needs & Contribution",
            "estimated_confidence_score": 99,
        })
        ai = _build_ai(response_json)
        result = ai.extract_structured_assumption("some text")
        assert result["estimated_confidence_score"] == 5


# ---------------------------------------------------------------------------
# Task 4 — Home tab rendering with new framework format
# ---------------------------------------------------------------------------


class TestHomeTabRendering:
    def _get_home_view(self, flow_stage="audit"):
        from blocks.home_tab import get_home_view
        from services.playbook_service import PlaybookService

        service = PlaybookService()
        project = {
            "id": 1,
            "name": "Test Project",
            "flow_stage": flow_stage,
            "assumptions": [],
            "experiments": [],
            "members": [],
            "integrations": {},
            "channel_id": None,
            "roadmap_plans": [],
        }
        return get_home_view(
            "U123",
            project,
            all_projects=[{"id": 1, "name": "Test Project"}],
            playbook_service=service,
        )

    def test_audit_view_contains_pillar_headers(self):
        view = self._get_home_view("audit")
        texts = [
            block.get("text", {}).get("text", "")
            for block in view["blocks"]
            if block.get("type") == "header"
        ]
        assert any("VALUE" in t for t in texts)
        assert any("FEASIBILITY" in t for t in texts)

    def test_audit_view_renders_answer_buttons(self):
        view = self._get_home_view("audit")
        answer_buttons = [
            block
            for block in view["blocks"]
            if block.get("accessory", {}).get("action_id") == "open_edit_diagnostic_answer"
        ]
        assert len(answer_buttons) > 0, "Should have ✏️ Answer buttons in audit view"

    def test_plan_view_has_roadmap_buttons(self):
        view = self._get_home_view("plan")
        roadmap_buttons = [
            block
            for block in view["blocks"]
            if block.get("accessory", {}).get("action_id") == "open_roadmap_modal"
        ]
        assert len(roadmap_buttons) > 0, "Should have 🗺️ Edit Roadmap buttons in plan view"

    def test_stepper_has_three_buttons(self):
        view = self._get_home_view("audit")
        stepper_blocks = [
            block for block in view["blocks"]
            if block.get("type") == "actions"
            and any(
                el.get("action_id") == "action_set_flow_stage"
                for el in block.get("elements", [])
            )
        ]
        assert len(stepper_blocks) == 1
        elements = stepper_blocks[0]["elements"]
        assert len(elements) == 3
        labels = [el["text"]["text"] for el in elements]
        assert "1️⃣ Audit" in labels
        assert "2️⃣ Plan" in labels
        assert "3️⃣ Action" in labels


# ---------------------------------------------------------------------------
# Task 5 — Modals
# ---------------------------------------------------------------------------


class TestModals:
    def test_diagnostic_modal_works_with_new_framework(self):
        from blocks.modals import get_diagnostic_modal
        from services.playbook_service import FULL_5_PILLAR_FRAMEWORK

        modal = get_diagnostic_modal(FULL_5_PILLAR_FRAMEWORK, project_id=1)
        assert modal["type"] == "modal"
        assert modal["callback_id"] == "action_save_diagnostic"
        # Should have input blocks for questions
        input_blocks = [b for b in modal["blocks"] if b.get("type") == "input"]
        assert len(input_blocks) > 0

    def test_edit_diagnostic_answer_modal(self):
        from blocks.modals import get_edit_diagnostic_answer_modal

        modal = get_edit_diagnostic_answer_modal(
            pillar="1. VALUE",
            sub_category="Needs & Contribution",
            question="Who is the target beneficiary?",
            answer="Parents with young children",
            confidence_score=3,
        )
        assert modal["type"] == "modal"
        assert modal["callback_id"] == "save_diagnostic_answer"

    def test_roadmap_modal(self):
        from blocks.modals import get_roadmap_modal

        modal = get_roadmap_modal("1. VALUE", "Needs & Contribution")
        assert modal["type"] == "modal"
        assert modal["callback_id"] == "save_roadmap_plan"
        # Should have 3 inputs: now, next, later
        input_blocks = [b for b in modal["blocks"] if b.get("type") == "input"]
        assert len(input_blocks) == 3


# ---------------------------------------------------------------------------
# Task 2b — Schema fixer
# ---------------------------------------------------------------------------


class TestSchemaFixer:
    def test_check_and_update_schema_runs_without_crash(self):
        from services.schema_fixer import check_and_update_schema

        # Should not raise on a fresh SQLite database
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            # Ensure Config.DATABASE_URL matches the patched environment and
            # reload schema_fixer so it picks up the updated configuration.
            import importlib
            import config
            from services import schema_fixer

            original_db_url = getattr(config.Config, "DATABASE_URL", None)
            try:
                config.Config.DATABASE_URL = f"sqlite:///{db_path}"
                importlib.reload(schema_fixer)
                from services.schema_fixer import check_and_update_schema as fresh_check
                fresh_check()  # Should not raise
            finally:
                if original_db_url is not None:
                    config.Config.DATABASE_URL = original_db_url
                else:
                    delattr(config.Config, "DATABASE_URL")
                importlib.reload(schema_fixer)
