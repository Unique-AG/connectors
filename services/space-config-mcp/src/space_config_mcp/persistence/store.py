import json
import logging
from typing import cast

import httpx
import unique_sdk

from space_config_mcp.persistence.settings import PersistenceSettings
from space_config_mcp.shared import SpaceConfigError

_LOGGER = logging.getLogger(__name__)
_MIME_TYPE = "application/json"
_HISTORY_FOLDER_NAME = "space-config-history"


class Persistence:
    """Content-store-backed snapshot store using KB file versioning.

    Each space has exactly one JSON file (``{space_id}.json``) inside a
    ``space-config-history`` sub-folder. Every ``snapshot_space`` call
    upserts that file with ``versioningEnabled=True``, creating a new
    version. The version history is the snapshot history.

    ``snapshot_id`` is the KB ``contentVersionId``, which uniquely
    identifies a version and can be passed back to ``version_download_url``
    to fetch the exact blob.

    The history folder is created on first use by listing the parent's
    children (using ``parentId``) and creating if missing. This avoids the
    ``folderPath`` lookup endpoint, which rejects bare names.

    Requires ``kb_scope_id`` — the scope ID of the parent KB folder (e.g.
    your skills-conduct folder). Find it via the Unique admin portal.
    """

    _kb_scope_id: str | None
    _history_folder_id: str | None

    def __init__(self, settings: PersistenceSettings) -> None:
        self._kb_scope_id = settings.kb_scope_id
        self._history_folder_id = None

    def _require_kb_scope_id(self) -> str:
        assert self._kb_scope_id, (
            "SPACE_CONFIG_MCP_KB_SCOPE_ID is not set. "
            "Set it to the scope ID of the parent KB folder (e.g. skills-conduct) "
            "under which the space-config-history sub-folder will be created."
        )
        return self._kb_scope_id

    async def _resolve_history_folder_id(self, user_id: str, company_id: str) -> str:
        """Return the history sub-folder scope ID, creating it when absent.

        Lists the parent folder's children by name rather than using the
        folderPath lookup endpoint, which returns 400 for bare folder names.
        """
        if self._history_folder_id:
            return self._history_folder_id

        parent_id = self._require_kb_scope_id()

        infos = await unique_sdk.Folder.get_infos_async(
            user_id,
            company_id,
            parentId=parent_id,
            take=200,
        )
        for folder in infos.get("folderInfos") or []:
            if folder.get("name") == _HISTORY_FOLDER_NAME:
                folder_id = folder.get("id")
                assert isinstance(folder_id, str) and folder_id
                self._history_folder_id = folder_id
                return folder_id

        result = await unique_sdk.Folder.create_paths_async(
            user_id,
            company_id,
            paths=[_HISTORY_FOLDER_NAME],
            parentScopeId=parent_id,
        )
        folders = result.get("createdFolders") or []
        assert folders, f"create_paths returned no folders for {_HISTORY_FOLDER_NAME!r}"
        folder_id = folders[-1].get("id")
        assert isinstance(folder_id, str) and folder_id, f"Folder created but id missing: {folders[-1]!r}"
        self._history_folder_id = folder_id
        return folder_id

    async def _resolve_content_id(
        self, user_id: str, company_id: str, space_id: str, folder_id: str
    ) -> str | None:
        """Return the content item ID for a space's snapshot file, or None."""
        result = await unique_sdk.Content.get_infos_async(
            user_id,
            company_id,
            parentId=folder_id,
            metadataFilter={"space_id": space_id},
            take=1,
        )
        infos = result.get("contentInfos") or []
        if not infos:
            return None
        content_id = infos[0].get("id")
        return content_id if isinstance(content_id, str) else None

    async def save_snapshot(
        self,
        user_id: str,
        company_id: str,
        *,
        space_id: str,
        snapshot_id: str,
        label: str,
        captured_at: str,
        config: dict[str, object],
    ) -> None:
        """Upsert the space's snapshot file, creating a new version.

        snapshot_id is stored in metadata for reference but the authoritative
        version identifier is the contentVersionId assigned by the KB.
        """
        folder_id = await self._resolve_history_folder_id(user_id, company_id)

        json_bytes = json.dumps(config, default=str).encode()
        key = f"{space_id}.json"
        title = f"{space_id} config history"
        metadata: dict[str, str] = {
            "space_id": space_id,
            "snapshot_id": snapshot_id,
            "label": label,
            "captured_at": captured_at,
        }

        ingestion_config = {"hideInChat": True, "uniqueIngestionMode": "SKIP_INGESTION"}

        initial = await unique_sdk.Content.upsert_async(
            user_id,
            company_id,
            input={
                "key": key,
                "title": title,
                "mimeType": _MIME_TYPE,
                "ingestionConfig": ingestion_config,
                "metadata": metadata,
            },
            scopeId=folder_id,
            versioningEnabled=True,
        )
        write_url = str(initial.writeUrl)
        async with httpx.AsyncClient() as http:
            response = await http.put(
                write_url,
                content=json_bytes,
                headers={
                    "X-Ms-Blob-Content-Type": _MIME_TYPE,
                    "X-Ms-Blob-Type": "BlockBlob",
                },
            )
        if response.status_code >= 400:
            raise SpaceConfigError(f"Blob upload failed with status {response.status_code}")

        await unique_sdk.Content.upsert_async(
            user_id,
            company_id,
            input={
                "key": key,
                "title": title,
                "mimeType": _MIME_TYPE,
                "byteSize": len(json_bytes),
                "ingestionConfig": ingestion_config,
                "metadata": metadata,
            },
            scopeId=folder_id,
            fileUrl=str(initial.readUrl),
            versioningEnabled=True,
        )

    async def delete_snapshots(
        self,
        user_id: str,
        company_id: str,
        space_id: str,
    ) -> None:
        """Delete all snapshots for a space by removing its snapshot file.

        This removes every version because the SDK does not expose individual
        version deletion — only the whole content item can be deleted.
        """
        folder_id = await self._resolve_history_folder_id(user_id, company_id)
        content_id = await self._resolve_content_id(user_id, company_id, space_id, folder_id)
        if content_id is None:
            return
        await unique_sdk.Content.delete_async(
            user_id,
            company_id,
            contentId=content_id,
        )
        _LOGGER.info("Deleted all snapshots for space %s (content %s)", space_id, content_id)

    async def list_snapshots(
        self,
        user_id: str,
        company_id: str,
        space_id: str,
    ) -> list[dict[str, object]]:
        try:
            folder_id = await self._resolve_history_folder_id(user_id, company_id)
            content_id = await self._resolve_content_id(user_id, company_id, space_id, folder_id)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("list_snapshots: folder or content not found: %s", exc)
            return []

        if content_id is None:
            return []

        versions = await unique_sdk.Content.versions_async(
            user_id,
            company_id,
            contentId=content_id,
            take=200,
        )

        rows: list[dict[str, object]] = []
        for v in versions.get("data") or []:
            rows.append(
                {
                    "snapshot_id": v.get("id") or "",
                    "version_number": v.get("versionNumber") or 0,
                    "label": v.get("title") or "",
                    "captured_at": v.get("originalCreatedAt") or v.get("archivedAt") or "",
                    "space_id": space_id,
                    "content_id": content_id,
                }
            )
        return sorted(rows, key=lambda x: int(x.get("version_number", 0)), reverse=True)

    async def get_snapshot(
        self,
        user_id: str,
        company_id: str,
        *,
        space_id: str,
        snapshot_id: str,
    ) -> dict[str, object]:
        """Download and return the config JSON for a specific version.

        snapshot_id is the KB contentVersionId returned by list_snapshots.
        """
        try:
            url_result = await unique_sdk.Content.version_download_url_async(
                user_id,
                company_id,
                contentVersionId=snapshot_id,
            )
        except Exception as exc:
            raise SpaceConfigError(f"Snapshot version {snapshot_id!r} not found") from exc

        download_url = url_result.get("url")
        assert isinstance(download_url, str) and download_url, f"No download URL for version {snapshot_id!r}"

        async with httpx.AsyncClient() as http:
            response = await http.get(download_url)
        if response.status_code != 200:
            raise SpaceConfigError(
                f"Failed to download snapshot {snapshot_id!r}: HTTP {response.status_code}"
            )

        raw: object = json.loads(response.content)  # pyright: ignore[reportAny] — json.loads is untyped
        assert isinstance(raw, dict), f"snapshot {snapshot_id!r} is not a JSON object"
        return cast(dict[str, object], raw)
