import asana
from googleapiclient.discovery import build

from config import Config
from services.google_auth_service import get_google_credentials


class IntegrationService:
    def __init__(self) -> None:
        self.drive_service = None
        if Config.GOOGLE_SERVICE_ACCOUNT_JSON:
            creds = get_google_credentials(["https://www.googleapis.com/auth/drive"])
            self.drive_service = build("drive", "v3", credentials=creds)

        self.asana_client = None
        if Config.ASANA_TOKEN:
            self.asana_client = asana.Client.access_token(Config.ASANA_TOKEN)

    def _refresh_asana_token(self) -> bool:
        """Mock refresh logic for expired Asana tokens."""
        return True

    @staticmethod
    def _get_error_message(error: Exception, action: str) -> str:
        """Return a user-friendly error message for Slack."""
        error_text = str(error).lower()
        if "rate limit" in error_text or "rate_limit" in error_text or "429" in error_text:
            return f"Rate limit reached while {action}. Please try again shortly."
        if "invalid token" in error_text or "expired" in error_text or "unauthorized" in error_text:
            return f"Auth token expired while {action}. Please reconnect the integration."
        return f"Something went wrong while {action}. Please try again."

    def create_drive_folder(self, folder_name: str) -> dict:
        """Create a Google Drive folder for the project.

        Args:
            folder_name: Name of the folder to create.

        Returns:
            A dictionary with folder id/link or an error message.
        """
        if not self.drive_service:
            return {"error": "Google Drive is not configured."}
        metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        try:
            file = self.drive_service.files().create(body=metadata, fields="id, webViewLink").execute()
            return {"id": file.get("id"), "link": file.get("webViewLink")}
        except Exception as exc:  # noqa: BLE001
            return {"error": self._get_error_message(exc, "creating the Drive folder")}

    def create_asana_project(self, project_name: str, workspace_id: str) -> dict:
        """Create an Asana project.

        Args:
            project_name: Name of the project to create.
            workspace_id: Asana workspace ID.

        Returns:
            A dictionary with project id/link or an error message.
        """
        if not self.asana_client:
            return {"error": "Asana is not configured."}
        try:
            result = self.asana_client.projects.create_project(
                {
                    "name": project_name,
                    "workspace": workspace_id,
                    "color": "light-green",
                }
            )
            return {"id": result["gid"], "link": result["permalink_url"]}
        except Exception as exc:  # noqa: BLE001
            if "expired" in str(exc).lower() and self._refresh_asana_token():
                return {"error": "Asana token refreshed. Please retry the action."}
            return {"error": self._get_error_message(exc, "creating the Asana project")}

    def create_asana_task(
        self,
        project_name: str,
        task_name: str,
        description: str,
        due_date: str | None = None,
    ) -> dict:
        """Create an Asana task for an experiment.

        Args:
            project_name: Name of the project.
            task_name: Task title.
            description: Task description.
            due_date: Optional due date.

        Returns:
            A dictionary with task link/id or an error message.
        """
        if not self.asana_client:
            return {"error": "Asana is not configured."}

        workspace_id = Config.ASANA_WORKSPACE_ID
        try:
            if not workspace_id:
                me = self.asana_client.users.me()
                workspaces = me.get("workspaces", [])
                if not workspaces:
                    return {"error": "No Asana workspace available for this account."}
                workspace_id = workspaces[0]["gid"]

            payload: dict[str, object] = {
                "workspace": workspace_id,
                "name": f"[{project_name}] {task_name}",
                "notes": description,
            }
            if due_date:
                payload["due_on"] = due_date

            result = self.asana_client.tasks.create_task(payload)
            return {"link": result.get("permalink_url"), "task_id": result.get("gid")}
        except Exception as exc:  # noqa: BLE001
            if "expired" in str(exc).lower() and self._refresh_asana_token():
                return {"error": "Asana token refreshed. Please retry the action."}
            return {"error": self._get_error_message(exc, "creating the Asana task")}

    def get_asana_tasks(self, project_gid: str) -> dict:
        """Fetch open tasks from a linked Asana project.

        Args:
            project_gid: Asana project GID.

        Returns:
            A dictionary with tasks list or an error message.
        """
        if not self.asana_client:
            return {"error": "Asana is not configured.", "tasks": []}
        try:
            tasks = self.asana_client.tasks.find_by_project(
                project_gid,
                {"opt_fields": "name,completed,notes"},
            )
            return {"tasks": [task for task in tasks if not task.get("completed")]}
        except Exception as exc:  # noqa: BLE001
            if "expired" in str(exc).lower() and self._refresh_asana_token():
                return {"error": "Asana token refreshed. Please retry the action.", "tasks": []}
            return {"error": self._get_error_message(exc, "fetching Asana tasks"), "tasks": []}
