from typing import Any


class TwoWaySyncService:
    """Resolve sync conflicts between Slack experiments and Asana tasks."""

    @staticmethod
    def resolve_status_conflict(experiment_status: str, asana_completed: bool) -> dict[str, Any]:
        """Determine how to handle conflicting completion statuses.

        Args:
            experiment_status: Current experiment status in Evidently.
            asana_completed: Whether the Asana task is completed.

        Returns:
            A decision payload describing the resolution path.
        """
        normalized_status = (experiment_status or "").lower()
        experiment_done = normalized_status in {"completed", "archived"}

        if experiment_done and asana_completed:
            return {"action": "noop", "message": "Both systems are already completed."}
        if experiment_done and not asana_completed:
            return {
                "action": "conflict",
                "message": "Experiment is completed in Slack, but Asana is still open.",
            }
        if not experiment_done and asana_completed:
            return {"action": "update_experiment", "message": "Asana completed task should close the experiment."}

        return {"action": "noop", "message": "No completion change detected."}
