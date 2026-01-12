import io
import logging
import re

import docx
import pdfplumber

logger = logging.getLogger(__name__)


class IngestionService:
    def extract_text(self, file_content: bytes, file_type: str) -> str | None:
        """Extract text from a supported file type.

        Args:
            file_content: Raw file bytes.
            file_type: MIME type string.

        Returns:
            Extracted text truncated to 50k characters, or None on failure.
        """
        text = ""
        try:
            file_stream = io.BytesIO(file_content)

            if "pdf" in file_type:
                with pdfplumber.open(file_stream) as pdf:
                    if pdf.is_encrypted:
                        logger.warning("Encrypted PDF detected")
                        return None
                    for page in pdf.pages:
                        text += (page.extract_text() or "") + "\n"

            elif "word" in file_type or "docx" in file_type:
                doc = docx.Document(file_stream)
                text = "\n".join([para.text for para in doc.paragraphs])

            elif "text" in file_type:
                text = file_content.decode("utf-8", errors="replace")

        except Exception:  # noqa: BLE001
            logger.exception("Extraction Error")
            return None

        return self.sanitize_text(text)[:50000]

    def extract_text_payload(self, file_content: bytes, file_type: str) -> dict:
        """Extract and chunk text for downstream ingestion.

        Args:
            file_content: Raw file bytes.
            file_type: MIME type string.

        Returns:
            Payload with extracted text, chunks, and optional error.
        """
        text = self.extract_text(file_content, file_type)
        if not text:
            return {
                "error": "Unable to extract text from that file. It may be encrypted or corrupted.",
                "text": "",
                "chunks": [],
            }
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
