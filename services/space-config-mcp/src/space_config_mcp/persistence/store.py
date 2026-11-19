import json
import logging
from typing import cast

import httpx
import unique_sdk

from space_config_mcp.persistence.settings import PersistenceSettings
from space_config_mcp.shared import SpaceConfigError

_LOGGER = logging.getLogger(__name__)
_MIME_TYPE = "application/json"


class Persistence:
    """Content-store-backed snapshot store using KB file versioning.

    Each space has exactly one JSON file (``{space_id}.json``) written
    directly into the KB scope set by ``SPACE_CONFIG_MCP_KB_SCOPE_ID``.
    Every ``snapshot_space`` call upserts that file with
    ``versioningEnabled=True``, creating a new version. The version
    history is the snapshot history.

    ``snapshot_id`` exposed to callers is the KB ``contentVersionId``,
    which can be passed to ``version_download_url`` to fetch the exact blob.

    Content items are located by ``metadataFilter={space_id: ...}`` so
    no folder-path resolution is needed — the scope ID is used directly.
    """

    _kb_scope_id: str | None

    def __init__(self, settings: PersistenceSettings) -> None:
        self._kb_scope_id = settings.kb_scope_id

    def _require_kb_scope_id(self) -> str:
        assert self._kb_scope_id, (
            "SPACE_CONFIG_MCP_KB_SCOPE_ID is not set. "
            "Set it to the scope ID of the KB folder where snapshots should be written."
        )
        return self._kb_scope_id

    async def _resolve_content_id(self, user_id: str, company_id: str, space_id: str) -> str | None:
        """Return the content item ID for a space's snapshot file, or None."""
        scope_id = self._require_kb_scope_id()
        result = await unique_sdk.Content.get_infos_async(
            user_id,
            company_id,
            metadataFilter={"space_id": space_id},
            take=1,
        )
        for item in result.get("contentInfos") or []:
            # Confirm it belongs to our scope to avoid collisions if the
            # metadataFilter matches content in other scopes.
            item_scope = item.get("scopeId") or item.get("readScopeId") or ""
            if scope_id in str(item_scope):
                content_id = item.get("id")
                if isinstance(content_id, str):  # pyright: ignore[reportUnnecessaryIsInstance]
                    return content_id
        # Fallback: accept any match when scopeId field is absent from the response.
        infos = result.get("contentInfos") or []
        if infos:
            content_id = infos[0].get("id")
            return content_id if isinstance(content_id, str) else None  # pyright: ignore[reportUnnecessaryIsInstance]
        return None

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
    ) -> str | None:
        """Upsert the space's snapshot file and return the new KB contentVersionId."""
        scope_id = self._require_kb_scope_id()

        json_bytes = json.dumps(config, default=str).encode()
        key = f"{space_id}_config.json"
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
                "ingestionConfig": ingestion_config,  # pyright: ignore[reportArgumentType]
                "metadata": metadata,
            },
            scopeId=scope_id,
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
                "ingestionConfig": ingestion_config,  # pyright: ignore[reportArgumentType]
                "metadata": metadata,
            },
            scopeId=scope_id,
            fileUrl=str(initial.readUrl),
            versioningEnabled=True,
        )

        try:
            content_id = await self._resolve_content_id(user_id, company_id, space_id)
            if content_id is None:
                return None
            versions = await unique_sdk.Content.versions_async(
                user_id, company_id, contentId=content_id, take=1
            )
            data = versions.get("data") or []
            if data:
                version_id = data[0].get("id")
                return str(version_id) if version_id else None
        except Exception:  # noqa: BLE001
            pass
        return None

    async def delete_snapshots(
        self,
        user_id: str,
        company_id: str,
        space_id: str,
    ) -> None:
        """Delete all snapshots for a space by removing its snapshot file and all versions."""
        content_id = await self._resolve_content_id(user_id, company_id, space_id)
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
            content_id = await self._resolve_content_id(user_id, company_id, space_id)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("list_snapshots: content not found: %s", exc)
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
        return sorted(
            rows,
            key=lambda x: int(x.get("version_number", 0)),  # pyright: ignore[reportArgumentType]
            reverse=True,
        )

    async def get_snapshot(
        self,
        user_id: str,
        company_id: str,
        *,
        space_id: str,
        snapshot_id: str,
    ) -> dict[str, object]:
        """Download and return the config JSON for a specific version."""
        content_id = await self._resolve_content_id(user_id, company_id, space_id)
        if content_id is not None:
            versions = await unique_sdk.Content.versions_async(
                user_id, company_id, contentId=content_id, take=200
            )
            valid_ids = {v.get("id") for v in (versions.get("data") or [])}
            if snapshot_id not in valid_ids:
                raise SpaceConfigError(
                    f"Snapshot {snapshot_id!r} does not belong to space {space_id!r}"
                )

        try:
            url_result = await unique_sdk.Content.version_download_url_async(
                user_id,
                company_id,
                contentVersionId=snapshot_id,
            )
        except Exception as exc:
            raise SpaceConfigError(f"Snapshot version {snapshot_id!r} not found") from exc

        download_url = url_result.get("url")
        assert isinstance(download_url, str) and download_url, (
            f"No download URL for version {snapshot_id!r}"
        )

        async with httpx.AsyncClient() as http:
            response = await http.get(download_url)
        if response.status_code != 200:
            raise SpaceConfigError(
                f"Failed to download snapshot {snapshot_id!r}: HTTP {response.status_code}"
            )

        raw: object = json.loads(response.content)  # pyright: ignore[reportAny] — json.loads is untyped
        assert isinstance(raw, dict), f"snapshot {snapshot_id!r} is not a JSON object"
        return cast(dict[str, object], raw)
