import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text

from services.db_service import engine

logger = logging.getLogger(__name__)


class BackupService:
    """Backup SQLite database tables to JSON."""

    def dump_database(self, output_dir: Path) -> Path | None:
        """Dump all tables to a JSON file.

        Args:
            output_dir: Directory to store the backup file.

        Returns:
            Path to the JSON file, or None on failure.
        """
        try:
            inspector = inspect(engine)
            data: dict[str, list[dict[str, Any]]] = {}
            with engine.connect() as connection:
                for table_name in inspector.get_table_names():
                    result = connection.execute(text(f"SELECT * FROM {table_name}"))
                    rows = [dict(row._mapping) for row in result.fetchall()]
                    data[table_name] = rows
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            output_path = output_dir / f"evidently-backup-{timestamp}.json"
            output_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
            return output_path
        except Exception:  # noqa: BLE001
            logger.exception("Failed to backup database")
            return None
