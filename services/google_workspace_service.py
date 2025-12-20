"""Wrapper around Google Workspace APIs for Docs, Sheets, Slides, and Gmail."""

from __future__ import annotations

import base64
import json
import logging
import uuid
from typing import Iterable, List

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import Config

logger = logging.getLogger(__name__)


class GoogleWorkspaceService:
    DOCS_SCOPE = "https://www.googleapis.com/auth/documents"
    SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
    SLIDES_SCOPE = "https://www.googleapis.com/auth/presentations"
    GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.send"
    DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"

    def __init__(self):
        self.creds = self._get_credentials()
        self.docs_service = build("docs", "v1", credentials=self.creds)
        self.sheets_service = build("sheets", "v4", credentials=self.creds)
        self.slides_service = build("slides", "v1", credentials=self.creds)
        self.gmail_service = build("gmail", "v1", credentials=self.creds)

    @staticmethod
    def _get_credentials():
        json_str = Config.GOOGLE_SERVICE_ACCOUNT_JSON
        if not json_str:
            raise ValueError("Missing GOOGLE_SERVICE_ACCOUNT_JSON in environment.")
        info = json.loads(json_str)
        scopes = [
            GoogleWorkspaceService.DOCS_SCOPE,
            GoogleWorkspaceService.SHEETS_SCOPE,
            GoogleWorkspaceService.SLIDES_SCOPE,
            GoogleWorkspaceService.GMAIL_SCOPE,
            GoogleWorkspaceService.DRIVE_SCOPE,
        ]
        return service_account.Credentials.from_service_account_info(info, scopes=scopes)

    def create_doc(self, title: str, content: str, share_email: str | None = None) -> str | None:
        try:
            body = {"title": title}
            document = self.docs_service.documents().create(body=body).execute()
            doc_id = document.get("documentId")
            requests = [{"insertText": {"location": {"index": 1}, "text": content}}]
            self.docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
            if share_email:
                self._share_file(doc_id, share_email)
            return f"https://docs.google.com/document/d/{doc_id}/edit"
        except HttpError:
            logger.error("Failed to create Google Doc", exc_info=True)
            return None
        except Exception:  # noqa: BLE001
            logger.error("Unexpected error creating Google Doc", exc_info=True)
            return None

    def create_sheet(self, title: str, headers: List[str], rows: Iterable[Iterable[str]]) -> str | None:
        try:
            sheet_body = {"properties": {"title": title}}
            spreadsheet = self.sheets_service.spreadsheets().create(body=sheet_body).execute()
            sheet_id = spreadsheet.get("spreadsheetId")
            data = [headers] + [list(row) for row in rows]
            self.sheets_service.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range="A1",
                valueInputOption="RAW",
                body={"values": data},
            ).execute()
            return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
        except HttpError:
            logger.error("Failed to create Google Sheet", exc_info=True)
            return None
        except Exception:  # noqa: BLE001
            logger.error("Unexpected error creating Sheet", exc_info=True)
            return None

    def create_slide_deck(self, title: str, slides_content: List[str], share_email: str | None = None) -> str | None:
        try:
            presentation = self.slides_service.presentations().create(body={"title": title}).execute()
            presentation_id = presentation.get("presentationId")
            requests = []
            for slide in slides_content:
                slide_id = f"slide_{uuid.uuid4().hex}"
                box_id = f"box_{uuid.uuid4().hex}"
                requests.append({"createSlide": {"objectId": slide_id}})
                requests.append(
                    {
                        "createShape": {
                            "objectId": box_id,
                            "shapeType": "TEXT_BOX",
                            "elementProperties": {"pageObjectId": slide_id},
                        }
                    }
                )
                requests.append(
                    {
                        "insertText": {
                            "objectId": box_id,
                            "insertionIndex": 0,
                            "text": slide,
                        }
                    }
                )
            if requests:
                self.slides_service.presentations().batchUpdate(
                    presentationId=presentation_id, body={"requests": requests}
                ).execute()
            if share_email:
                self._share_file(presentation_id, share_email)
            return f"https://docs.google.com/presentation/d/{presentation_id}/edit"
        except HttpError:
            logger.error("Failed to create slide deck", exc_info=True)
            return None
        except Exception:  # noqa: BLE001
            logger.error("Unexpected error creating slides", exc_info=True)
            return None

    def _share_file(self, file_id: str, email: str, role: str = "writer") -> None:
        try:
            drive_service = build("drive", "v3", credentials=self.creds)
            drive_service.permissions().create(
                fileId=file_id,
                body={"type": "user", "role": role, "emailAddress": email},
                fields="id",
                sendNotificationEmail=False,
            ).execute()
        except HttpError:
            logger.error("Failed to share file %s with %s", file_id, email, exc_info=True)
        except Exception:  # noqa: BLE001
            logger.error("Unexpected error sharing file %s", file_id, exc_info=True)

    def send_email(self, to: str, subject: str, body: str) -> bool:
        try:
            message = f"To: {to}\nSubject: {subject}\n\n{body}"
            encoded_message = base64.urlsafe_b64encode(message.encode("utf-8")).decode("utf-8")
            send_body = {"raw": encoded_message}
            self.gmail_service.users().messages().send(userId="me", body=send_body).execute()
            return True
        except HttpError:
            logger.error("Failed to send email", exc_info=True)
            return False
        except Exception:  # noqa: BLE001
            logger.error("Unexpected error sending email", exc_info=True)
            return False
