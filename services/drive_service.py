import logging
import os
import re

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from services.google_auth_service import get_google_credentials

logger = logging.getLogger(__name__)


class DriveService:
    SCOPES = [
        "https://www.googleapis.com/auth/drive.metadata.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/documents.readonly",
    ]

    def __init__(self):
        self.creds = None
        self.drive_service = None
        self.docs_service = None
        try:
            self.creds = self._get_credentials()
            if self.creds:
                self.drive_service = build("drive", "v3", credentials=self.creds)
                self.docs_service = build("docs", "v1", credentials=self.creds)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to initialize Google Drive clients: %s", exc)

    def _get_credentials(self):
        allow_file_fallback = os.path.exists("service_account.json")
        return get_google_credentials(self.SCOPES, allow_file_fallback=allow_file_fallback)

    def get_file_content(self, file_id: str) -> str | None:
        if not self.docs_service:
            return None
        try:
            document = self.docs_service.documents().get(documentId=file_id).execute()
            content = document.get("body", {}).get("content")
            return self._read_structural_elements(content)
        except HttpError:
            logger.error("Failed to read Google Doc %s", file_id, exc_info=True)
            return None
        except Exception:
            logger.error("Unexpected error reading Google Doc %s", file_id, exc_info=True)
            return None

    def get_file_metadata(self, file_id: str) -> dict | None:
        if not self.drive_service:
            return None
        try:
            return self.drive_service.files().get(
                fileId=file_id,
                fields="id, name, mimeType, webViewLink",
            ).execute()
        except Exception:
            logger.error("Failed to read Google Drive metadata for %s", file_id, exc_info=True)
            return None

    def _read_structural_elements(self, elements):
        text_parts = []
        if not elements:
            return ""

        for value in elements:
            if "paragraph" in value:
                paragraph = value.get("paragraph", {})
                para_elements = paragraph.get("elements", [])
                for elem in para_elements:
                    text_parts.append(elem.get("textRun", {}).get("content", ""))
            elif "table" in value:
                table = value.get("table", {})
                for row in table.get("tableRows", []):
                    for cell in row.get("tableCells", []):
                        text_parts.append(self._read_structural_elements(cell.get("content", [])))
                        text_parts.append(" | ")
                    text_parts.append("\n")
        return "".join(text_parts)

    def extract_id_from_url(self, url: str) -> tuple[str | None, str | None]:
        if not url:
            return None, None

        folder_match = re.search(r"folders/([a-zA-Z0-9-_]+)", url)
        if folder_match:
            return folder_match.group(1), "drive_folder"

        file_match = re.search(r"/d/([a-zA-Z0-9-_]+)", url)
        if file_match:
            return file_match.group(1), "drive_file"

        cleaned = url.strip()
        if re.fullmatch(r"[a-zA-Z0-9-_]+", cleaned):
            return cleaned, "drive_file"

        return None, None
