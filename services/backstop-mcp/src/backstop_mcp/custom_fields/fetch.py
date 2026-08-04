from __future__ import annotations

from typing import cast

from backstop_mcp.backstop_client.client import BackstopClient
from backstop_mcp.backstop_client.json_api import BackstopApiResource
from backstop_mcp.config import CustomFieldOverrideConfig
from backstop_mcp.custom_fields.overrides import index_overrides, normalize_entity_type
from backstop_mcp.custom_fields.types import (
    AllowedValue,
    CustomFieldDefinition,
    CustomFieldDefinitionAttributes,
)


def _as_object_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return cast(dict[str, object], value)


def _as_object_list(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    return cast(list[object], value)


def _label_from_option(option: object) -> str | None:
    if isinstance(option, str):
        text = option.strip()
        return text or None
    option_dict = _as_object_dict(option)
    if option_dict is None:
        return None
    for key in ("label", "name", "value", "displayName", "display_name"):
        value = option_dict.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    option_id = option_dict.get("id")
    if option_id is not None:
        return str(option_id)
    return None


def _id_from_option(option: object) -> str | None:
    option_dict = _as_object_dict(option)
    if option_dict is None or option_dict.get("id") is None:
        return None
    return str(option_dict["id"])


def extract_allowed_values(
    lov_set: object | None,
    select_options: object | None,
) -> tuple[AllowedValue, ...]:
    """Best-effort LOV / selectOptions → AllowedValue list."""
    values: list[AllowedValue] = []
    seen: set[str] = set()

    def add(option: object) -> None:
        label = _label_from_option(option)
        if label is None or label in seen:
            return
        seen.add(label)
        values.append(AllowedValue(id=_id_from_option(option), label=label))

    for option in _as_object_list(select_options):
        add(option)

    lov_dict = _as_object_dict(lov_set)
    if lov_dict is not None:
        for key in ("entries", "lovEntries", "options", "values"):
            for option in _as_object_list(lov_dict.get(key)):
                add(option)
        data = lov_dict.get("data")
        data_list = _as_object_list(data)
        if data_list:
            for item in data_list:
                item_dict = _as_object_dict(item)
                if item_dict is None:
                    add(item)
                    continue
                attrs = item_dict.get("attributes", item)
                add(attrs if _as_object_dict(attrs) is not None else item)
        else:
            data_dict = _as_object_dict(data)
            if data_dict is not None:
                attrs = data_dict.get("attributes", data)
                add(attrs if _as_object_dict(attrs) is not None else data)
    else:
        for option in _as_object_list(lov_set):
            add(option)

    return tuple(values)


def definition_from_resource(
    resource: BackstopApiResource[CustomFieldDefinitionAttributes],
    overrides: dict[tuple[str, str], CustomFieldOverrideConfig],
) -> CustomFieldDefinition | None:
    attrs = resource.attributes
    crm_name = (attrs.name or "").strip()
    if not crm_name:
        return None

    entity_raw = (attrs.entity_type or "").strip()
    if not entity_raw:
        return None
    entity_type = normalize_entity_type(entity_raw)

    override = overrides.get((entity_type, crm_name))

    display_name = (
        override.display_name.strip()
        if override is not None and override.display_name
        else crm_name
    )
    aliases = tuple(
        a.strip() for a in (override.aliases if override is not None else []) if a.strip()
    )
    description = (
        override.description if override is not None and override.description else attrs.description
    )

    return CustomFieldDefinition(
        definition_id=resource.id,
        entity_type=entity_type,
        crm_name=crm_name,
        display_name=display_name,
        aliases=aliases,
        description=description,
        field_type=attrs.field_type,
        field_type_display=attrs.field_type_display,
        is_time_series=bool(attrs.is_time_series),
        allowed_values=extract_allowed_values(attrs.lov_set, attrs.select_options),
        raw={
            "id": resource.id,
            "type": resource.type,
            "attributes": attrs.model_dump(by_alias=True, exclude_none=True),
        },
    )


def definitions_from_overrides_only(
    overrides: dict[str, CustomFieldOverrideConfig],
) -> list[CustomFieldDefinition]:
    """Seed definitions from env overrides when CRM snapshot is not yet loaded."""
    result: list[CustomFieldDefinition] = []
    for (entity_type, crm_name), override in index_overrides(overrides).items():
        display = (override.display_name or crm_name).strip()
        result.append(
            CustomFieldDefinition(
                definition_id=crm_name,
                entity_type=entity_type,
                crm_name=crm_name,
                display_name=display,
                aliases=tuple(a.strip() for a in override.aliases if a.strip()),
                description=override.description,
                is_time_series=False,
                allowed_values=(),
                raw={},
            )
        )
    return result


async def fetch_custom_field_definitions(
    client: BackstopClient,
    overrides: dict[str, CustomFieldOverrideConfig],
) -> list[CustomFieldDefinition]:
    """Paginate all custom-field definitions with lovSet included."""
    page = await client.paginate(
        "/custom-field-definitions",
        params={"include": "lovSet"},
        schema=BackstopApiResource[CustomFieldDefinitionAttributes],
    )
    override_index = index_overrides(overrides)
    definitions: list[CustomFieldDefinition] = []
    for resource in page.items:
        definition = definition_from_resource(resource, override_index)
        if definition is not None:
            definitions.append(definition)
    return definitions
