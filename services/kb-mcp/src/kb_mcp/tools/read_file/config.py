"""Admin-set RJSF config for the read_file tool."""

from pydantic import BaseModel


class ReadFileToolConfig(BaseModel):
    max_tokens_per_call: int = 8_000
