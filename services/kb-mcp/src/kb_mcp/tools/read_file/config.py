"""Admin-set RJSF config for the read_file tool."""

from pydantic import BaseModel, Field


class ReadFileToolConfig(BaseModel):
    max_tokens_per_call: int = Field(default=8_000, gt=0)
