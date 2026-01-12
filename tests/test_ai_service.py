import unittest
from unittest.mock import MagicMock, patch

from services.ai_service import EvidenceAI


class TestEvidenceAI(unittest.TestCase):
    @patch("services.ai_service.genai.configure")
    def test_generate_canvas_from_doc_handles_failure(self, _configure):
        ai = EvidenceAI()
        ai.model = MagicMock()
        ai.model.generate_content.side_effect = Exception("API failure")

        result = ai.generate_canvas_from_doc("Sample document")

        self.assertEqual(result["canvas_data"]["problem"], "")
        self.assertEqual(result["gaps_identified"], [])

    @patch("services.ai_service.genai.configure")
    def test_scout_market_handles_failure(self, _configure):
        ai = EvidenceAI()
        ai.model = MagicMock()
        ai.model.generate_content.side_effect = Exception("API failure")

        result = ai.scout_market("Problem statement", region="UK")

        self.assertEqual(result["competitors"], [])
        self.assertEqual(result["risks"], [])
