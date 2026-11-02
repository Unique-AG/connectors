import json
import logging
from typing import cast

import httpx
import unique_sdk

from space_config_mcp.persistence.settings import PersistenceSettings
from space_config_mcp.shared import SpaceConfigError

_LOGGER = logging.getLogger(__name__)
_MIME_TYPE = "application/json"
_PAGE_SIZE = 200


class Persistence:
    """Content-store-backed snapshot store for space configurations.

    Each snapshot is stored as an application/json blob under
    ``{history_folder}/{space_id}/{snapshot_id}`` in the platform
    knowledge base. The folder is marked hideInChat so its contents
    never surface in chat search results.

    Snapshots are point-in-time captures. Config changes made through
    the portal between MCP calls are not reflected until the next
    snapshot_space call.
    """

    _folder: str

    def __init__(self, settings: PersistenceSettings) -> None:
        self._folder = settings.history_folder

    def _folder_path(self, space_id: str) -> str:
        return f"{self._folder}/{space_id}"

    def _content_key(self, snapshot_id: str) -> str:
        return snapshot_id

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
        json_bytes = json.dumps(config, default=str).encode()
        folder_path = self._folder_path(space_id)
        key = self._content_key(snapshot_id)
        metadata: dict[str, str] = {
            "space_id": space_id,
            "snapshot_id": snapshot_id,
            "label": label,
            "captured_at": captured_at,
        }

        initial = await unique_sdk.Content.upsert_async(
            user_id,
            company_id,
            input={
                "key": key,
                "title": label,
                "mimeType": _MIME_TYPE,
                "metadata": metadata,
            },
            parentFolderPath=folder_path,
            createFolderIfNotExists=True,
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
                "title": label,
                "mimeType": _MIME_TYPE,
                "byteSize": len(json_bytes),
                "metadata": metadata,
            },
            parentFolderPath=folder_path,
            fileUrl=str(initial.readUrl),
            versioningEnabled=True,
        )

        await unique_sdk.Folder.update_ingestion_config_async(
            user_id=user_id,
            company_id=company_id,
            folderPath=folder_path,
            ingestionConfig={"hideInChat": True},
            applyToSubScopes=False,
        )

    async def list_snapshots(
        self,
        user_id: str,
        company_id: str,
        space_id: str,
    ) -> list[dict[str, object]]:
        folder_path = self._folder_path(space_id)
        try:
            result = await unique_sdk.Content.get_infos_async(
                user_id,
                company_id,
                parentFolderPath=folder_path,
                take=_PAGE_SIZE,
            )
        except Exception as exc:  # noqa: BLE001 — SDK raises unspecified errors for missing folder
            _LOGGER.debug("list_snapshots: folder not found or empty: %s", exc)
            return []

        rows: list[dict[str, object]] = []
        for info in result.get("contentInfos") or []:
            meta = info.get("metadata") or {}
            snapshot_id = meta.get("snapshot_id") or info.get("key", "")
            rows.append(
                {
                    "snapshot_id": snapshot_id,
                    "label": meta.get("label") or info.get("title") or "",
                    "captured_at": meta.get("captured_at") or info.get("createdAt") or "",
                    "space_id": meta.get("space_id") or space_id,
                    "content_id": info.get("id") or "",
                }
            )
        return sorted(rows, key=lambda x: str(x.get("captured_at", "")), reverse=True)

    async def get_snapshot(
        self,
        user_id: str,
        company_id: str,
        *,
        space_id: str,
        snapshot_id: str,
    ) -> dict[str, object]:
        folder_path = self._folder_path(space_id)
        try:
            result = await unique_sdk.Content.get_infos_async(
                user_id,
                company_id,
                parentFolderPath=folder_path,
                metadataFilter={"snapshot_id": snapshot_id},
                take=1,
            )
        except Exception as exc:
            raise SpaceConfigError(f"Snapshot {snapshot_id!r} not found") from exc

        infos = result.get("contentInfos") or []
        if not infos:
            raise SpaceConfigError(f"Snapshot {snapshot_id!r} not found")

        content_id = infos[0].get("id")
        assert isinstance(content_id, str), f"content_id missing for snapshot {snapshot_id!r}"

        download_url = f"{unique_sdk.api_base.rstrip('/')}/content/{content_id}/file"
        headers: dict[str, str] = {
            "x-api-version": unique_sdk.api_version,
            "x-user-id": user_id,
            "x-company-id": company_id,
        }
        if unique_sdk.app_id:
            headers["x-app-id"] = str(unique_sdk.app_id)
        if unique_sdk.api_key:
            headers["Authorization"] = f"Bearer {unique_sdk.api_key}"

        async with httpx.AsyncClient() as http:
            response = await http.get(download_url, headers=headers)
        if response.status_code != 200:
            raise SpaceConfigError(
                f"Failed to download snapshot {snapshot_id!r}: HTTP {response.status_code}"
            )

        raw: object = json.loads(response.content)  # pyright: ignore[reportAny] — json.loads is untyped
        assert isinstance(raw, dict), f"snapshot {snapshot_id!r} is not a JSON object"
        return cast(dict[str, object], raw)
