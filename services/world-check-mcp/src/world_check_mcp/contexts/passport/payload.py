from datetime import date

from world_check_mcp.contexts.passport.errors import PassportError
from world_check_mcp.contexts.passport.models import Passport
from world_check_mcp.contexts.screening import FieldValue
from world_check_mcp.contexts.screening import normalized
from world_check_mcp.contexts.screening import validate_fields
from world_check_mcp.upstream import CaseTemplateResponse
from world_check_mcp.upstream import FieldDefinition

_PASSPORT_FIELDS = (
    ("given_name", "GIVEN_NAME", "TEXT"),
    ("last_name", "LAST_NAME", "TEXT"),
    ("gender", "GENDER", "GENDER"),
    ("issuing_state", "ISSUING_STATE", "STATE"),
    ("nationality", "NATIONALITY", "STATE"),
    ("date_of_birth", "DATE_OF_BIRTH", "DATE"),
    ("document_type", "DOCUMENT_TYPE", "PASSPORT_DOCUMENT_TYPE"),
    ("identification_number", "IDENTIFICATION_NUMBER", "TEXT"),
    ("date_of_expiry", "DATE_OF_EXPIRY", "DATE"),
)


def passport_arguments(
    *,
    passport: Passport,
    name: str,
    group_id: str,
    template: CaseTemplateResponse,
    countries: dict[str, str],
    nationalities: dict[str, str],
    case_id: str | None,
    include_watchlist: bool,
    secondary_fields: list[FieldValue],
    custom_fields: list[FieldValue],
) -> dict[str, object]:
    """Passport Check save-and-screen body. Media Check is never requested."""
    _require_case_group(template=template, group_id=group_id)
    providers = ["WATCHLIST", "PASSPORT_CHECK"] if include_watchlist else ["PASSPORT_CHECK"]
    mandatory = {normalized(value=provider) for provider in template.mandatory_provider_types or []}
    if not mandatory.issubset(providers):
        raise PassportError(
            "The group requires additional providers. Enable include_watchlist or choose another "
            "group. Media Check is unsupported."
        )
    passport_definitions = _entity_fields(template=template, provider="PASSPORT_CHECK")
    watchlist_definitions = (
        _entity_fields(template=template, provider="WATCHLIST") if include_watchlist else []
    )
    definitions = [*passport_definitions, *watchlist_definitions]
    provided = [
        *secondary_fields,
        *_passport_fields(passport=passport, definitions=passport_definitions),
    ]
    body: dict[str, object] = {
        "name": name,
        "entityType": "INDIVIDUAL",
        "groupId": group_id,
        "providerTypes": providers,
        "secondaryFields": validate_fields(
            fields=provided,
            definitions=definitions,
            countries=countries,
            nationalities=nationalities,
        ),
        "customFields": validate_fields(
            fields=custom_fields,
            definitions=template.custom_fields or [],
            countries=countries,
            nationalities=nationalities,
        ),
        "screen": "SYNC",
    }
    if include_watchlist:
        body["caseScreeningState"] = {"WATCHLIST": "INITIAL"}
    if case_id is not None:
        body["caseId"] = case_id
    return body


def _passport_fields(*, passport: Passport, definitions: list[FieldDefinition]) -> list[FieldValue]:
    """The passport's values under the typeIds the group's PASSPORT_CHECK fields carry, found by
    label as screening does, since the ids differ between groups.
    """
    values: dict[str, date | str] = {
        "given_name": passport.given_name,
        "last_name": passport.last_name,
        "gender": passport.gender,
        "issuing_state": passport.issuing_state,
        "nationality": passport.nationality,
        "date_of_birth": passport.date_of_birth,
        "document_type": passport.document_type,
        "identification_number": passport.identification_number,
        "date_of_expiry": passport.date_of_expiry,
    }
    fields: list[FieldValue] = []
    for attribute, label, value_type in _PASSPORT_FIELDS:
        matches = [
            field
            for field in definitions
            if normalized(value=field.label) == label and field.field_value_type == value_type
        ]
        if len(matches) != 1:
            raise PassportError(
                f"Cannot uniquely map passport field {label} ({value_type}). "
                "See get_group_settings."
            )
        type_id = matches[0].type_id
        value = values[attribute]
        if isinstance(value, date):
            fields.append(FieldValue(type_id=type_id, date_time_value=value))
        else:
            text = value.upper() if value_type == "STATE" else value
            fields.append(FieldValue(type_id=type_id, value=text))
    return fields


def _entity_fields(*, template: CaseTemplateResponse, provider: str) -> list[FieldDefinition]:
    by_provider = template.secondary_fields_by_provider or {}
    matched = [fields for name, fields in by_provider.items() if normalized(value=name) == provider]
    if len(matched) != 1:
        raise PassportError(f"This group does not uniquely define {provider} secondary fields.")
    individuals = [
        fields
        for name, fields in matched[0].secondary_fields_by_entity.items()
        if normalized(value=name) == "INDIVIDUAL"
    ]
    if len(individuals) != 1:
        raise PassportError(f"This group does not uniquely define {provider} individual fields.")
    return individuals[0]


def _require_case_group(*, template: CaseTemplateResponse, group_id: str) -> None:
    if template.group_id != group_id or template.group_screening_type != "CASE_MANAGEMENT_AUDIT":
        raise PassportError("Passport Check requires a persistent case-management group.")
