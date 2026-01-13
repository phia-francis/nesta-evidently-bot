import datetime as dt
import logging
from typing import Any
from urllib.parse import urlencode

import requests

from config import Config

logger = logging.getLogger(__name__)


class GoogleService:
    _AUTH_BASE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    _TOKEN_URL = "https://oauth2.googleapis.com/token"
    _DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"

    def __init__(self) -> None:
        self.client_id = Config.GOOGLE_CLIENT_ID
        self.client_secret = Config.GOOGLE_CLIENT_SECRET
        self.redirect_uri = Config.GOOGLE_REDIRECT_URI

    def get_auth_url(self, project_id: int) -> str:
        if not self.client_id or not self.redirect_uri:
            raise ValueError("Google OAuth client settings are missing.")
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "https://www.googleapis.com/auth/drive.readonly",
            "access_type": "offline",
            "prompt": "consent",
            "state": str(project_id),
        }
        return f"{self._AUTH_BASE_URL}?{urlencode(params)}"

    def exchange_code(self, code: str) -> dict[str, Any]:
        if not self.client_id or not self.client_secret or not self.redirect_uri:
            raise ValueError("Google OAuth client settings are missing.")
        payload = {
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
        }
        response = requests.post(self._TOKEN_URL, data=payload, timeout=20)
        response.raise_for_status()
        return response.json()

    def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        if not self.client_id or not self.client_secret:
            raise ValueError("Google OAuth client settings are missing.")
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        response = requests.post(self._TOKEN_URL, data=payload, timeout=20)
        response.raise_for_status()
        return response.json()

    def fetch_file_content(self, file_id: str, access_token: str) -> str:
        file_metadata = self._get_file_metadata(file_id, access_token)
        mime_type = file_metadata.get("mimeType", "")
        export_url = f"{self._DRIVE_FILES_URL}/{file_id}/export"

        if mime_type == "application/vnd.google-apps.document":
            params = {"mimeType": "text/plain"}
            return self._download_content(export_url, access_token, params=params)

        if mime_type == "application/vnd.google-apps.spreadsheet":
            params = {"mimeType": "text/csv"}
            return self._download_content(export_url, access_token, params=params)

        if mime_type == "application/vnd.google-apps.presentation":
            params = {"mimeType": "text/plain"}
            return self._download_content(export_url, access_token, params=params)

        if mime_type == "application/pdf":
            return "PDF parsing is not yet supported. Please copy and use Magic Paste."

        if mime_type == "text/plain":
            download_url = f"{self._DRIVE_FILES_URL}/{file_id}"
            params = {"alt": "media"}
            return self._download_content(download_url, access_token, params=params)

        raise ValueError(f"Unsupported file type: {mime_type}")

    def _get_file_metadata(self, file_id: str, access_token: str) -> dict[str, Any]:
        url = f"{self._DRIVE_FILES_URL}/{file_id}"
        params = {"fields": "id,name,mimeType"}
        response = requests.get(url, headers=self._auth_headers(access_token), params=params, timeout=20)
        response.raise_for_status()
        return response.json()

    def _download_content(self, url: str, access_token: str, params: dict[str, Any]) -> str:
        response = requests.get(url, headers=self._auth_headers(access_token), params=params, timeout=20)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        if "application/pdf" in content_type:
            logger.warning("Returning raw PDF content as text; consider adding a PDF text extractor.")
            return response.content.decode("latin-1", errors="ignore")
        return response.text

    def token_is_expired(self, token_expiry: dt.datetime | None) -> bool:
        if not token_expiry:
            return False
        return dt.datetime.utcnow() >= token_expiry

    @staticmethod
    def _auth_headers(access_token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {access_token}"}
