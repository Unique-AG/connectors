import re
from collections.abc import Mapping
from datetime import datetime
from typing import Literal, Self

from msgraph.generated.models.column_definition import ColumnDefinition
from msgraph.generated.models.list_item import ListItem
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import MAX_SCANNED_ITEMS, collect_pages
from office_365_mcp.shared.handles import ListHandle, ListItemHandle

ColumnType = Literal[
    "boolean",
    "calculated",
    "choice",
    "contentApprovalStatus",
    "currency",
    "dateTime",
    "geolocation",
    "hyperlinkOrPicture",
    "lookup",
    "number",
    "personOrGroup",
    "term",
    "text",
    "thumbnail",
    "other",
]

_FACETS: tuple[tuple[ColumnType, str], ...] = (
    ("boolean", "boolean"),
    ("calculated", "calculated"),
    ("choice", "choice"),
    ("contentApprovalStatus", "content_approval_status"),
    ("currency", "currency"),
    ("dateTime", "date_time"),
    ("geolocation", "geolocation"),
    ("hyperlinkOrPicture", "hyperlink_or_picture"),
    ("lookup", "lookup"),
    ("number", "number"),
    ("personOrGroup", "person_or_group"),
    ("term", "term"),
    ("text", "text"),
    ("thumbnail", "thumbnail"),
)

NOT_A_LIST_HANDLE = (
    "takes a list handle: the `uri` of a row from sharepoint_list_lists, copied exactly. A list "
    + "title is not a handle. Nor is a web address. If you call this tool again with the same "
    + "arguments, the call will fail the same way."
)

VALUE_TYPES: frozenset[ColumnType] = frozenset(
    {"text", "choice", "dateTime", "number", "currency", "boolean"}
)
_NUMBER_TYPES: frozenset[ColumnType] = frozenset({"number", "currency"})
_PLAIN_DECIMAL = re.compile(r"-?\d+(?:\.\d+)?")

type FieldValue = str | int | float | bool

FIELDS_RULES = (
    "Key each value by the internal `name` of its column, not its display name. Write every "
    + "value as text: a number as a plain decimal such as 12.5, a yes or no value as true or "
    + "false, a date as 2026-01-31T00:00:00Z, and a choice as one of the `choices` of its column."
)


class ListColumn(BaseModel):
    name: str | None = Field(
        description=(
            "The internal name of the column. It is the key of this column in the `fields` of an "
            + "item, and the name to pass as `column` to filter items. Null when Graph sent none."
        )
    )
    display_name: str | None = Field(
        description="The name SharePoint shows for the column. Null when Graph sent none."
    )
    type: ColumnType = Field(
        description=(
            "The kind of value the column holds, as Graph names it. The value `other` means a "
            + "kind this tool does not recognize."
        )
    )
    required: bool | None = Field(
        description="True when every item needs a value here. Null when Graph sent nothing."
    )
    read_only: bool | None = Field(
        description="True when nobody can edit the value. Null when Graph sent nothing."
    )
    hidden: bool | None = Field(
        description=(
            "True when SharePoint hides the column from forms. Null when Graph sent nothing."
        )
    )
    indexed: bool | None = Field(
        description=(
            "True when the column is indexed. Only an indexed column can be used to filter "
            + "items. Null when Graph sent nothing."
        )
    )
    choices: list[str] | None = Field(
        description="The allowed values of a choice column. Null for every other type."
    )

    @classmethod
    def from_column(cls, column: ColumnDefinition) -> Self:
        return cls(
            name=column.name,
            display_name=column.display_name,
            type=_column_type(column),
            required=column.required,
            read_only=column.read_only,
            hidden=column.hidden,
            indexed=column.indexed,
            choices=None if column.choice is None else list(column.choice.choices or []),
        )


def _column_type(column: ColumnDefinition) -> ColumnType:
    for name, field in _FACETS:
        if getattr(column, field) is not None:
            return name
    return "other"


async def list_columns(client: GraphServiceClient, handle: ListHandle) -> list[ListColumn]:
    first_page = (
        await client.sites.by_site_id(handle.site_id).lists.by_list_id(handle.list_id).columns.get()
    )
    assert first_page is not None, "Graph answered a column listing with no collection"
    collected = await collect_pages(first_page, client, limit=MAX_SCANNED_ITEMS)
    return [ListColumn.from_column(column) for column in collected.items]


class ListItemSummary(BaseModel):
    uri: str = Field(description="The handle of this item. Copy it exactly. Never build one.")
    fields: dict[str, object] = Field(
        description=(
            "The column values of the item, keyed by internal column name, as Microsoft "
            + "returned them."
        )
    )
    web_url: str | None = Field(
        description=(
            "The address that opens the item in a browser. Give it to the user when you answer "
            + "about this item. Null when Graph recorded none."
        )
    )
    last_modified_at: datetime | None = Field(
        description="When the item last changed. Null when Graph recorded none."
    )

    @classmethod
    def from_item(cls, handle: ListHandle, item: ListItem) -> Self:
        assert item.id is not None, "an item without an id reached the row builder"
        # The SDK lifts `id` out of `fields`, so it goes back in beside the custom columns.
        fields = item.fields
        values: dict[str, object] = {} if fields is None else dict(fields.additional_data)
        if fields is not None and fields.id is not None:
            values = {"id": fields.id, **values}
        return cls(
            uri=ListItemHandle(handle.site_id, handle.list_id, item.id).uri,
            fields=values,
            web_url=item.web_url,
            last_modified_at=item.last_modified_date_time,
        )


def value_refusal(column: ListColumn, value: str) -> str | None:
    assert column.type in VALUE_TYPES, f"a {column.type} column has no value to spell"
    if column.type in _NUMBER_TYPES and not _PLAIN_DECIMAL.fullmatch(value):
        return f"The column {column.name!r} holds numbers. Pass a plain decimal."
    if column.type == "boolean" and value not in {"true", "false"}:
        return f"The column {column.name!r} is yes or no. Pass true or false."
    return None


def _typed(column: ListColumn, value: str) -> FieldValue:
    if column.type in _NUMBER_TYPES:
        return float(value) if "." in value else int(value)
    if column.type == "boolean":
        return value == "true"
    return value


def written_fields(
    columns: list[ListColumn], fields: Mapping[str, str], *, nothing_happened: str
) -> dict[str, FieldValue] | str:
    by_name = {column.name: column for column in columns if column.name is not None}
    written: dict[str, FieldValue] = {}
    for name, value in fields.items():
        refusal = _write_refusal(by_name.get(name), name, value)
        if refusal is not None:
            return f"{nothing_happened} {refusal}"
        written[name] = _typed(by_name[name], value)
    return written


def _write_refusal(column: ListColumn | None, name: str, value: str) -> str | None:
    if column is None:
        return (
            f"This list has no column with the internal name {name!r}. Call sharepoint_get_list "
            + "and pass the `name` of a column, not its display name."
        )
    if column.read_only is True or column.hidden is True:
        return f"The column {name!r} is read-only or hidden, so this connector does not write it."
    if column.type not in VALUE_TYPES:
        return (
            f"This connector cannot write the column {name!r}, because its type is "
            + f"{column.type}. It writes text, choice, date, number, currency, and yes or no "
            + "columns. Tell the user to change this column in SharePoint."
        )
    choices = column.choices or []
    if column.type == "choice" and value not in choices:
        return (
            f"The column {name!r} takes one of these choices: "
            + f"{', '.join(repr(choice) for choice in choices)}."
        )
    return value_refusal(column, value)
