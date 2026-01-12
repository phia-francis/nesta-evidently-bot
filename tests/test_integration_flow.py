import importlib
import os
import tempfile
import unittest
from pathlib import Path


class TestIntegrationFlow(unittest.TestCase):
    def test_project_flow_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "evidently_test.db"
            os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

            from services import db_service
            from services.toolkit_service import ToolkitService

            importlib.reload(db_service)

            service = db_service.DbService()
            user_id = "U123"
            project = service.create_project(user_id=user_id, name="Test Project", description="Test", stage="Define")
            project_data = service.get_active_project(user_id)
            self.assertIsNotNone(project_data)
            self.assertGreaterEqual(len(project_data["assumptions"]), 1)
            self.assertGreaterEqual(len(project_data["experiments"]), 1)

            assumption = service.create_assumption(
                project_id=project.id,
                data={"title": "We can recruit participants via local partners."},
            )
            experiment = service.create_experiment(
                project_id=project.id,
                title="Partner interviews",
                method=ToolkitService.DEFAULT_METHOD_NAME,
                hypothesis="We can schedule five interviews in one week.",
            )
            service.update_assumption_validation_status(assumption.id, "Validated")
            service.update_experiment(experiment.id, status="Completed")

            metrics = service.get_metrics(project.id)
            self.assertGreaterEqual(metrics["experiments"], 2)
            self.assertGreaterEqual(metrics["validated"], 1)

            updated_experiment = service.get_experiment(experiment.id)
            self.assertIsNotNone(updated_experiment)
            self.assertEqual(updated_experiment["status"], "Completed")


if __name__ == "__main__":
    unittest.main()
