from typing import ClassVar

from pydantic import BaseModel, ConfigDict

__all__ = ["AggregateBucketDto"]


class AggregateBucketDto(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    key: str
    label: str
    count: int
