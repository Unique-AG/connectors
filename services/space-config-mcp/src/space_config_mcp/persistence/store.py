from datetime import datetime
from datetime import UTC
import json
from pathlib import Path
from typing import cast
import uuid

from space_config_mcp.shared import SpaceConfigError


class Persistence:
    """File-backed JSON snapshot store for space configurations."""

    _path: Path

    def __init__(self, store_path: str) -> None:
        self._path = Path(store_path)

    def _load(self) -> dict[str, object]:
        if not self._path.exists():
            return {}
        return cast(dict[str, object], json.loads(self._path.read_text()))

    def _save(self, store: dict[str, object]) -> None:
        self._path.write_text(json.dumps(store, default=str))

    def save_snapshot(
        self,
        space_data: dict[str, object],
        *,
        label: str,
    ) -> dict[str, str]:
        snapshot_id = str(uuid.uuid4())
        space_id = str(space_data.get("id", ""))
        resolved_label = label or f"snapshot-{datetime.now(UTC).isoformat()}"
        entry: dict[str, object] = {
            **space_data,
            "_snapshot_id": snapshot_id,
            "_label": resolved_label,
            "_captured_at": datetime.now(UTC).isoformat(),
            "_space_id": space_id,
        }
        store = self._load()
        store[snapshot_id] = entry
        self._save(store)
        return {"snapshot_id": snapshot_id, "label": resolved_label}

    def list_snapshots(
        self,
        *,
        space_id: str | None = None,
    ) -> list[dict[str, object]]:
        store = self._load()
        results: list[dict[str, object]] = []
        for v in store.values():
            if not isinstance(v, dict):
                continue
            row = cast(dict[str, object], v)
            if space_id is not None and row.get("_space_id") != space_id:
                continue
            results.append(
                {
                    "snapshot_id": cast(str, row["_snapshot_id"]),
                    "label": cast(str, row["_label"]),
                    "captured_at": cast(str, row["_captured_at"]),
                    "space_id": cast(str, row["_space_id"]),
                }
            )
        return sorted(results, key=lambda x: str(x.get("captured_at", "")), reverse=True)

    def get_snapshot(self, snapshot_id: str) -> dict[str, object]:
        store = self._load()
        if snapshot_id not in store:
            raise SpaceConfigError(f"Snapshot {snapshot_id!r} not found")
        entry = store[snapshot_id]
        assert isinstance(entry, dict), f"snapshot {snapshot_id!r} is not a dict"
        return cast(dict[str, object], entry)
