import os
import json
import logging
from google.oauth2 import service_account
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

class DriveService:
    SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

    def __init__(self):
        self.creds = self._get_credentials()
        self.drive_service = build('drive', 'v3', credentials=self.creds)
        self.docs_service = build('docs', 'v1', credentials=self.creds)

    def _get_credentials(self):
        """Loads credentials from the environment variable string."""
        json_str = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        if not json_str:
            raise ValueError("Missing GOOGLE_SERVICE_ACCOUNT_JSON in environment.")
        
        info = json.loads(json_str)
        return service_account.Credentials.from_service_account_info(
            info, scopes=self.SCOPES
        )

    def get_file_content(self, file_id: str) -> str | None:
        """
        Fetches text content from a Google Doc.
        """
        try:
            # Retrieve the document structure
            document = self.docs_service.documents().get(documentId=file_id).execute()
            content = document.get('body').get('content')
            return self._read_structural_elements(content)
        except HttpError as e:
            logger.error(f"Failed to read Google Doc {file_id}: {e}")
            return None

    def _read_structural_elements(self, elements):
        """Recursively extracts text from the confusing Google Docs JSON structure."""
        text_parts = []
        if not elements:
            return ""

        for value in elements:
            if 'paragraph' in value:
                paragraph = value.get('paragraph', {})
                para_elements = paragraph.get('elements', [])
                for elem in para_elements:
                    text_parts.append(elem.get('textRun', {}).get('content', ''))
            elif 'table' in value:
                # Basic table support: flatten the text
                table = value.get('table', {})
                for row in table.get('tableRows', []):
                    for cell in row.get('tableCells', []):
                        text_parts.append(self._read_structural_elements(cell.get('content', [])))
                        text_parts.append(" | ")
                    text_parts.append("\n")
        return "".join(text_parts)

    def extract_id_from_url(self, url: str) -> str:
        """Parses a Google Doc URL to find the File ID."""
        # URL format: https://docs.google.com/document/d/FILE_ID/edit
        try:
            if "/d/" in url:
                return url.split("/d/")[1].split("/")[0]
            return url # Assume it is the ID if no URL structure found
except Exception:
            return None
