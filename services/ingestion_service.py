import asyncio
import io
import logging
import re

import docx
import pdfplumber
from pypdf.errors import PdfReadError

from services.drive_service import DriveService
from services.db_service import DbService

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 50 * 1024 * 1024


class IngestionError(Exception):
    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


class IngestionService:
    def __init__(self, db_service: DbService | None = None, drive_service: DriveService | None = None) -> None:
        self.db_service = db_service
        self.drive_service = drive_service or DriveService()

    def extract_text(self, file_content: bytes, file_type: str) -> str | None:
        """Extract text from a supported file type.

        Args:
            file_content: Raw file bytes.
            file_type: MIME type string.

        Returns:
            Extracted text truncated to 50k characters, or None on failure.
        """
        if len(file_content) > MAX_FILE_BYTES:
            raise IngestionError("That file is too large to process. Please upload files under 50MB.")

        text = ""
        try:
            file_stream = io.BytesIO(file_content)

            if "pdf" in file_type:
                with pdfplumber.open(file_stream) as pdf:
                    if pdf.is_encrypted:
                        logger.warning("Encrypted PDF detected")
                        raise IngestionError("That PDF is encrypted and can't be processed.")
                    for page in pdf.pages:
                        text += (page.extract_text() or "") + "\n"

            elif "word" in file_type or "docx" in file_type:
                doc = docx.Document(file_stream)
                text = "\n".join([para.text for para in doc.paragraphs])

            elif "text" in file_type:
                text = file_content.decode("utf-8", errors="replace")

        except PdfReadError:
            logger.warning("Corrupted PDF detected", exc_info=True)
            raise IngestionError("That PDF appears to be corrupted. Please upload a different file.")
        except Exception:  # noqa: BLE001
            logger.exception("Extraction Error")
            raise IngestionError("Unable to extract text from that file. Please try another file.")

        return self.sanitize_text(text)[:50000]

    async def process_drive_files_async(self, project_id: int) -> str:
        if not self.db_service:
            logger.warning("DbService missing for drive processing.")
            return ""
        project = self.db_service.get_project(project_id)
        if not project:
            return ""
        integrations = project.get("integrations") or {}
        drive_info = integrations.get("drive") or {}
        files = drive_info.get("files") or []
        if not files:
            return ""

        content_parts: list[str] = []
        for file_item in files:
            file_id = file_item.get("id")
            if not file_id:
                continue
            mime_type = file_item.get("mime_type")
            if not mime_type:
                metadata = await asyncio.to_thread(self.drive_service.get_file_metadata, file_id) or {}
                mime_type = metadata.get("mimeType")
            if not mime_type:
                continue

            if "google-apps.document" in mime_type:
                text = await asyncio.to_thread(self.drive_service.get_file_content, file_id)
                if text:
                    content_parts.append(text)
                continue

            file_bytes = await asyncio.to_thread(self.drive_service.download_file, file_id)
            if not file_bytes:
                continue
            try:
                text = self.extract_text(file_bytes, mime_type)
                if text:
                    content_parts.append(text)
            except IngestionError as exc:
                logger.warning("Drive file %s skipped: %s", file_id, exc.user_message)

        return "\n".join(content_parts).strip()

    def ingest_project_files(self, project_id: int) -> str:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.process_drive_files_async(project_id))
        future = asyncio.run_coroutine_threadsafe(self.process_drive_files_async(project_id), loop)
        return future.result()

    def extract_text_payload(self, file_content: bytes, file_type: str) -> dict:
        """Extract and chunk text for downstream ingestion.

        Args:
            file_content: Raw file bytes.
            file_type: MIME type string.

        Returns:
            Payload with extracted text, chunks, and optional error.
        """
        try:
            text = self.extract_text(file_content, file_type)
        except IngestionError as exc:
            return {"error": exc.user_message, "text": "", "chunks": []}
        if not text:
            return {"error": "Unable to extract text from that file.", "text": "", "chunks": []}
        chunks = self.chunk_text(text)
        return {"text": text, "chunks": chunks}

    @staticmethod
    def sanitize_text(text: str) -> str:
        """Sanitize extracted text by removing control characters."""
        cleaned = re.sub(r"[\x00-\x08\x0b-\x1f]", " ", text)
        return re.sub(r"\s+", " ", cleaned).strip()

    @staticmethod
    def chunk_text(text: str, max_chars: int = 3500) -> list[str]:
        """Split text into chunks to fit context windows."""
        if not text:
            return []
        return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]
