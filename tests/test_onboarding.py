import unittest

from blocks.onboarding import ProjectPhase


class TestProjectPhase(unittest.TestCase):
    def test_members_have_value_and_display_text(self) -> None:
        self.assertEqual(ProjectPhase.DISCOVERY.value, "Discovery")
        self.assertEqual(ProjectPhase.DISCOVERY.display_text, "Discovery (Understanding needs)")

        self.assertEqual(ProjectPhase.ALPHA.value, "Alpha")
        self.assertEqual(ProjectPhase.ALPHA.display_text, "Alpha (Testing solutions)")

        self.assertEqual(ProjectPhase.BETA.value, "Beta")
        self.assertEqual(ProjectPhase.BETA.display_text, "Beta (Scaling)")


if __name__ == "__main__":
    unittest.main()
