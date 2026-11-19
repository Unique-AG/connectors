from typing import override

from fastmcp.utilities.types import File


class FileFromGraph(File):
    def __init__(self, content: bytes, *, name: str | None, mime_type: str) -> None:
        self.mime_type: str = mime_type
        super().__init__(data=content, name=name)

    @override
    def _get_mime_type(self) -> str:
        return self.mime_type
