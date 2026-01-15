from services.ingestion_service import IngestionService


class DummyDbService:
    def __init__(self, project: dict) -> None:
        self._project = project

    def get_project(self, _project_id: int):
        return self._project


class DummyDriveService:
    def __init__(self, doc_text: str, pdf_bytes: bytes) -> None:
        self._doc_text = doc_text
        self._pdf_bytes = pdf_bytes

    def get_file_metadata(self, _file_id: str):
        return None

    def get_file_content(self, _file_id: str):
        return self._doc_text

    def download_file(self, _file_id: str):
        return self._pdf_bytes


def test_ingest_project_files_combines_doc_and_pdf(monkeypatch):
    project = {
        "integrations": {
            "drive": {
                "files": [
                    {"id": "doc1", "mime_type": "application/vnd.google-apps.document"},
                    {"id": "pdf1", "mime_type": "application/pdf"},
                ]
            }
        }
    }
    ingestion = IngestionService(
        db_service=DummyDbService(project),
        drive_service=DummyDriveService("doc text", b"%PDF-1.4"),
    )
    monkeypatch.setattr(ingestion, "extract_text", lambda *_args, **_kwargs: "pdf text")
    result = ingestion.ingest_project_files(1)
    assert "doc text" in result
    assert "pdf text" in result
