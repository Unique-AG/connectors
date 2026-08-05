from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, cast, final

from unique_sdk import APIRequestor

from q_bridge_mcp.config.settings import settings
from q_bridge_mcp.profiles.models import OrganizationCredentials

PAGE_SIZE = 100


@dataclass(frozen=True)
class FolderNode:
    id: str
    name: str
    parent_id: str | None


@dataclass(frozen=True)
class ContentNode:
    id: str
    key: str
    mime_type: str
    updated_at: str | None


class KnowledgeBaseClient(Protocol):
    async def resolve_root_folder(self, folder_path: str) -> FolderNode: ...

    async def list_folders(self, parent_id: str) -> list[FolderNode]: ...

    async def list_contents(self, parent_id: str) -> list[ContentNode]: ...

    async def download_content(self, content_id: str) -> bytes: ...


@final
class UniqueKnowledgeBaseClient:
    def __init__(self, requestor: APIRequestor) -> None:
        self._requestor = requestor

    @classmethod
    def create(
        cls,
        *,
        user_id: str,
        company_id: str,
        credentials: OrganizationCredentials,
    ) -> UniqueKnowledgeBaseClient:
        requestor = APIRequestor(
            user_id=user_id,
            company_id=company_id,
            key=credentials.api_key,
            app_id=credentials.app_id,
        )
        requestor.api_base = str(settings.unique_api_base_url).rstrip("/")
        return cls(requestor)

    async def resolve_root_folder(self, folder_path: str) -> FolderNode:
        normalized_path = f"/{folder_path.strip('/')}"
        response = await self._requestor.request_async(
            "get",
            "/folder/info",
            {"folderPath": normalized_path},
        )
        return self._to_folder(self._mapping(response.data))

    async def list_folders(self, parent_id: str) -> list[FolderNode]:
        folders: list[FolderNode] = []
        skip = 0
        while True:
            response = await self._requestor.request_async(
                "get",
                "/folder/infos",
                {"parentId": parent_id, "skip": skip, "take": PAGE_SIZE},
            )
            data = self._mapping(response.data)
            page = self._mapping_list(data.get("folderInfos"))
            folders.extend(self._to_folder(item) for item in page)
            skip += len(page)
            if skip >= self._integer(data.get("totalCount")) or not page:
                return folders

    async def list_contents(self, parent_id: str) -> list[ContentNode]:
        contents: list[ContentNode] = []
        skip = 0
        while True:
            response = await self._requestor.request_async(
                "post",
                "/content/infos",
                {"parentId": parent_id, "skip": skip, "take": PAGE_SIZE},
            )
            data = self._mapping(response.data)
            page = self._mapping_list(data.get("contentInfos"))
            contents.extend(self._to_content(item) for item in page)
            skip += len(page)
            if skip >= self._integer(data.get("totalCount")) or not page:
                return contents

    async def download_content(self, content_id: str) -> bytes:
        body, status, headers = await self._requestor.request_raw_async(
            "get",
            f"/content/{content_id}/file",
        )
        if not 200 <= status < 300:
            _ = self._requestor.interpret_response(body, status, headers)
        if isinstance(body, bytes):
            return body
        if isinstance(body, str):
            return body.encode()
        raise TypeError(f"Unexpected content response type: {type(body).__name__}")

    @staticmethod
    def _mapping(value: object) -> Mapping[str, object]:
        if not isinstance(value, Mapping):
            raise TypeError("Unique API response must be an object")
        return cast(Mapping[str, object], value)

    @classmethod
    def _mapping_list(cls, value: object) -> list[Mapping[str, object]]:
        if not isinstance(value, list):
            raise TypeError("Unique API response page must be a list")
        return [cls._mapping(item) for item in value]

    @staticmethod
    def _string(value: object) -> str:
        if not isinstance(value, str) or not value:
            raise TypeError("Unique API response field must be a non-empty string")
        return value

    @staticmethod
    def _optional_string(value: object) -> str | None:
        return value if isinstance(value, str) else None

    @staticmethod
    def _integer(value: object) -> int:
        if not isinstance(value, int):
            raise TypeError("Unique API response totalCount must be an integer")
        return value

    @classmethod
    def _to_folder(cls, value: Mapping[str, object]) -> FolderNode:
        return FolderNode(
            id=cls._string(value.get("id")),
            name=cls._string(value.get("name")),
            parent_id=cls._optional_string(value.get("parentId")),
        )

    @classmethod
    def _to_content(cls, value: Mapping[str, object]) -> ContentNode:
        return ContentNode(
            id=cls._string(value.get("id")),
            key=cls._string(value.get("key")),
            mime_type=cls._string(value.get("mimeType")),
            updated_at=cls._optional_string(value.get("updatedAt")),
        )
