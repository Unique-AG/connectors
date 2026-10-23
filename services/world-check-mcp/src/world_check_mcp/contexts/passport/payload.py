from datetime import date

from pydantic.alias_generators import to_snake

from world_check_mcp.contexts.passport.errors import PassportError
from world_check_mcp.contexts.passport.models import Passport
from world_check_mcp.contexts.screening import FieldValue
from world_check_mcp.contexts.screening import ScreeningError
from world_check_mcp.contexts.screening import validate_fields
from world_check_mcp.upstream import CaseTemplateResponse
from world_check_mcp.upstream import FieldDefinition

_PASSPORT_FIELDS = (
    ("given_name", "SFCT_8", "TEXT"),
    ("last_name", "SFCT_9", "TEXT"),
    ("gender", "SFCT_10", "GENDER"),
    ("issuing_state", "SFCT_11", "STATE"),
    ("nationality", "SFCT_12", "STATE"),
    ("date_of_birth", "SFCT_13", "DATE"),
    ("document_type", "SFCT_14", "PASSPORT_DOCUMENT_TYPE"),
    ("identification_number", "SFCT_15", "TEXT"),
    ("date_of_expiry", "SFCT_16", "DATE"),
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
    mandatory = {_normalized(value=provider) for provider in template.mandatoryProviderTypes or []}
    if not mandatory.issubset(providers):
        raise ScreeningError(
            "The group requires additional providers. Enable include_watchlist or choose another "
            "group. Media Check is unsupported."
        )
    definitions = _entity_fields(template=template, provider="PASSPORT_CHECK")
    if include_watchlist:
        definitions = [*definitions, *_entity_fields(template=template, provider="WATCHLIST")]
    provided = [
        *secondary_fields,
        *_passport_fields(passport=passport, definitions=definitions),
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
            definitions=template.customFields or [],
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
    available = {field.typeId: field for field in definitions}
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
    for attribute, type_id, value_type in _PASSPORT_FIELDS:
        definition = available.get(type_id)
        if definition is None or definition.fieldValueType != value_type:
            raise PassportError(
                f"The group does not expose passport field {type_id} ({value_type}). "
                "See get_group_settings."
            )
        value = values[attribute]
        if isinstance(value, date):
            fields.append(FieldValue(type_id=type_id, date_time_value=value))
        else:
            text = value.upper() if value_type == "STATE" else value
            fields.append(FieldValue(type_id=type_id, value=text))
    return fields


def _entity_fields(*, template: CaseTemplateResponse, provider: str) -> list[FieldDefinition]:
    by_provider = template.secondaryFieldsByProvider or {}
    matched = [
        fields for name, fields in by_provider.items() if _normalized(value=name) == provider
    ]
    if len(matched) != 1:
        raise PassportError(f"This group does not uniquely define {provider} secondary fields.")
    individuals = [
        fields
        for name, fields in matched[0].secondaryFieldsByEntity.items()
        if _normalized(value=name) == "INDIVIDUAL"
    ]
    if len(individuals) != 1:
        raise PassportError(f"This group does not uniquely define {provider} individual fields.")
    return individuals[0]


def _require_case_group(*, template: CaseTemplateResponse, group_id: str) -> None:
    if template.groupId != group_id or template.groupScreeningType != "CASE_MANAGEMENT_AUDIT":
        raise ScreeningError("Passport Check requires a persistent case-management group.")


def _normalized(*, value: str) -> str:
    return to_snake(value).upper().replace(" ", "_")
