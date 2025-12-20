import json
import logging
import os

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


class DriveService:
    SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

    def __init__(self):
        try:
            self.creds = self._get_credentials()
            self.drive_service = build("drive", "v3", credentials=self.creds)
            self.docs_service = build("docs", "v1", credentials=self.creds)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to initialize Google Drive clients", exc_info=True)
            raise

    def _get_credentials(self):
        """Loads credentials from the environment variable string."""
        json_str = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        if not json_str:
            raise ValueError("Missing GOOGLE_SERVICE_ACCOUNT_JSON in environment.")

        info = json.loads(json_str)
        return service_account.Credentials.from_service_account_info(info, scopes=self.SCOPES)

    def get_file_content(self, file_id: str) -> str | None:
        """Fetch text content from a Google Doc."""
        try:
            document = self.docs_service.documents().get(documentId=file_id).execute()
            content = document.get("body", {}).get("content")
            return self._read_structural_elements(content)
        except HttpError as exc:
            logger.error("Failed to read Google Doc %s", file_id, exc_info=True)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.error("Unexpected error reading Google Doc %s", file_id, exc_info=True)
            return None

    def _read_structural_elements(self, elements):
        """Recursively extracts text from the Google Docs JSON structure."""
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

    def extract_id_from_url(self, url: str) -> str | None:
        """Parses a Google Doc URL to find the File ID."""
        try:
            if "/d/" in url:
                return url.split("/d/")[1].split("/")[0]
            return url
        except Exception:  # noqa: BLE001
            return None
