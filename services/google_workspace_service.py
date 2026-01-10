"""Wrapper around Google Workspace APIs for Docs, Sheets, Slides, and Gmail."""

from __future__ import annotations

import base64
import logging
import uuid
from typing import Iterable, List

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from services.google_auth_service import get_google_credentials

logger = logging.getLogger(__name__)


class GoogleWorkspaceService:
    DOCS_SCOPE = "https://www.googleapis.com/auth/documents"
    SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
    SLIDES_SCOPE = "https://www.googleapis.com/auth/presentations"
    GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.send"

    def __init__(self):
        self.creds = self._get_credentials()
        self.docs_service = build("docs", "v1", credentials=self.creds)
        self.sheets_service = build("sheets", "v4", credentials=self.creds)
        self.slides_service = build("slides", "v1", credentials=self.creds)
        self.gmail_service = build("gmail", "v1", credentials=self.creds)

    @staticmethod
    def _get_credentials():
        scopes = [
            GoogleWorkspaceService.DOCS_SCOPE,
            GoogleWorkspaceService.SHEETS_SCOPE,
            GoogleWorkspaceService.SLIDES_SCOPE,
            GoogleWorkspaceService.GMAIL_SCOPE,
        ]
        return get_google_credentials(scopes, require=True)

    def create_doc(self, title: str, content: str) -> str | None:
        try:
            body = {"title": title}
            document = self.docs_service.documents().create(body=body).execute()
            doc_id = document.get("documentId")
            requests = [{"insertText": {"location": {"index": 1}, "text": content}}]
            self.docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
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

    def create_slide_deck(self, title: str, slides_content: List[str]) -> str | None:
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
            return f"https://docs.google.com/presentation/d/{presentation_id}/edit"
        except HttpError:
            logger.error("Failed to create slide deck", exc_info=True)
            return None
        except Exception:  # noqa: BLE001
            logger.error("Unexpected error creating slides", exc_info=True)
            return None

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
