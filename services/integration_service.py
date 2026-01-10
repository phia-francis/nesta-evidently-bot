import os

import asana
from google.oauth2 import service_account
from googleapiclient.discovery import build

from config import Config


class IntegrationService:
    def __init__(self) -> None:
        self.drive_service = None
        if os.path.exists("service_account.json"):
            creds = service_account.Credentials.from_service_account_file(
                "service_account.json",
                scopes=["https://www.googleapis.com/auth/drive"],
            )
            self.drive_service = build("drive", "v3", credentials=creds)

        self.asana_client = None
        if Config.ASANA_TOKEN:
            self.asana_client = asana.Client.access_token(Config.ASANA_TOKEN)

    def create_drive_folder(self, folder_name: str) -> dict | None:
        if not self.drive_service:
            return None
        metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        file = self.drive_service.files().create(body=metadata, fields="id, webViewLink").execute()
        return {"id": file.get("id"), "link": file.get("webViewLink")}

    def create_asana_project(self, project_name: str, workspace_id: str) -> dict | None:
        if not self.asana_client:
            return None
        result = self.asana_client.projects.create_project(
            {
                "name": project_name,
                "workspace": workspace_id,
                "color": "light-green",
            }
        )
        return {"id": result["gid"], "link": result["permalink_url"]}
