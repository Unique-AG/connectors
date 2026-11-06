from typing import ClassVar

from mcp_openapi.upstream import Operation
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import TypeAdapter


class CaseWire(BaseModel):
    """The case fields these tools read. Hand-written: the generated Case narrows optional base
    fields, which the type check rejects as an incompatible override.
    Pinned by tests/test_spec_overrides.py.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    case_id: str | None = Field(default=None, alias="caseId")
    case_system_id: str | None = Field(default=None, alias="caseSystemId")
    name: str
    entity_type: str = Field(alias="entityType")
    group_id: str = Field(alias="groupId")
    provider_types: list[str] = Field(alias="providerTypes")
    lifecycle_state: str | None = Field(default=None, alias="lifecycleState")


GET_CASE = Operation[CaseWire]("getCase", TypeAdapter(CaseWire))
