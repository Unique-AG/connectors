from datetime import date

from pydantic.alias_generators import to_snake

from world_check_mcp.contexts.screening.errors import ScreeningError
from world_check_mcp.contexts.screening.models import EntityType
from world_check_mcp.contexts.screening.models import FieldValue
from world_check_mcp.contexts.screening.models import Gender
from world_check_mcp.upstream import CaseTemplateResponse
from world_check_mcp.upstream import FieldDefinition

_LABELS = (
    "DATE_OF_BIRTH",
    "NATIONALITY",
    "COUNTRY_OF_RESIDENCE",
    "PLACE_OF_BIRTH",
    "REGISTERED_COUNTRY",
    "GENDER",
)
_DOCUMENTS = frozenset({"PASSPORT", "ID1", "ID2"})
_GENDERS = frozenset({"MALE", "FEMALE", "UNSPECIFIED"})


def check_entity(
    *,
    entity_type: EntityType,
    dob: date | None,
    nationality: str | None,
    country_of_residence: str | None,
    place_of_birth: str | None,
    registered_country: str | None,
    gender: Gender | None,
    case_id: str | None,
) -> None:
    if dob is not None and dob > date.today():
        raise ScreeningError("Date of birth cannot be in the future.")
    if case_id is not None and (
        case_id.startswith("/") or case_id.endswith("/") or "//" in case_id
    ):
        raise ScreeningError(
            "case_id cannot start or end with a slash or contain consecutive slashes."
        )
    individual = (dob, nationality, country_of_residence, place_of_birth, gender)
    if entity_type == "ORGANISATION" and any(value is not None for value in individual):
        raise ScreeningError("Use registered_country for organizations, not individual fields.")
    if entity_type == "INDIVIDUAL" and registered_country is not None:
        raise ScreeningError("registered_country is only valid for organizations.")


def screening_arguments(
    *,
    name: str,
    entity_type: EntityType,
    group_id: str,
    template: CaseTemplateResponse,
    countries: dict[str, str],
    nationalities: dict[str, str],
    case_id: str | None,
    dob: date | None,
    nationality: str | None,
    country_of_residence: str | None,
    place_of_birth: str | None,
    registered_country: str | None,
    gender: Gender | None,
    secondary_fields: list[FieldValue],
    custom_fields: list[FieldValue],
) -> dict[str, object]:
    """WATCHLIST save-and-screen body. Media Check is never requested."""
    _require_watchlist_group(template=template, group_id=group_id)
    definitions = _definitions(template=template, entity_type=entity_type)
    provided = _with_named_fields(
        definitions=definitions,
        secondary_fields=secondary_fields,
        dob=dob,
        nationality=_upper(value=nationality),
        country_of_residence=_upper(value=country_of_residence),
        place_of_birth=_upper(value=place_of_birth),
        registered_country=_upper(value=registered_country),
        gender=gender,
    )
    body: dict[str, object] = {
        "name": name,
        "entityType": entity_type,
        "groupId": group_id,
        "providerTypes": ["WATCHLIST"],
        "caseScreeningState": {"WATCHLIST": "INITIAL"},
        "secondaryFields": _validate(
            fields=provided,
            definitions=definitions,
            countries=countries,
            nationalities=nationalities,
        ),
        "customFields": _validate(
            fields=custom_fields,
            definitions=template.customFields or [],
            countries=countries,
            nationalities=nationalities,
        ),
        "screen": "SYNC",
    }
    if case_id is not None:
        body["caseId"] = case_id
    return body


def _require_watchlist_group(*, template: CaseTemplateResponse, group_id: str) -> None:
    if template.groupId != group_id or template.groupScreeningType != "CASE_MANAGEMENT_AUDIT":
        raise ScreeningError("Choose a case-management group. screen_entity persists a case.")
    mandatory = template.mandatoryProviderTypes or []
    if any(_normalized(value=provider) != "WATCHLIST" for provider in mandatory):
        raise ScreeningError(
            "This group requires other providers. Choose a WATCHLIST-only group, "
            "or use passport_check for Passport Check."
        )


def _definitions(*, template: CaseTemplateResponse, entity_type: str) -> list[FieldDefinition]:
    by_provider = template.secondaryFieldsByProvider or {}
    watchlist = [
        fields for name, fields in by_provider.items() if _normalized(value=name) == "WATCHLIST"
    ]
    if len(watchlist) != 1:
        raise ScreeningError("This group does not uniquely define WATCHLIST secondary fields.")
    matches = [
        fields
        for name, fields in watchlist[0].secondaryFieldsByEntity.items()
        if _normalized(value=name) == entity_type
    ]
    if len(matches) != 1:
        raise ScreeningError(f"This group does not uniquely define {entity_type} secondary fields.")
    return matches[0]


def _with_named_fields(
    *,
    definitions: list[FieldDefinition],
    secondary_fields: list[FieldValue],
    dob: date | None,
    nationality: str | None,
    country_of_residence: str | None,
    place_of_birth: str | None,
    registered_country: str | None,
    gender: Gender | None,
) -> list[FieldValue]:
    named = {
        "DATE_OF_BIRTH": dob,
        "NATIONALITY": nationality,
        "COUNTRY_OF_RESIDENCE": country_of_residence,
        "PLACE_OF_BIRTH": place_of_birth,
        "REGISTERED_COUNTRY": registered_country,
        "GENDER": gender,
    }
    added: list[FieldValue] = []
    for label in _LABELS:
        value = named[label]
        if value is None:
            continue
        matches = [field for field in definitions if _normalized(value=field.label) == label]
        if len(matches) != 1:
            raise ScreeningError(f"Cannot uniquely map {label}. See get_group_settings.")
        if label == "DATE_OF_BIRTH":
            added.append(FieldValue(type_id=matches[0].typeId, date_time_value=dob))
        else:
            added.append(FieldValue(type_id=matches[0].typeId, value=str(value)))
    return [*secondary_fields, *added]


def _validate(
    *,
    fields: list[FieldValue],
    definitions: list[FieldDefinition],
    countries: dict[str, str],
    nationalities: dict[str, str],
) -> list[dict[str, str]]:
    available = {field.typeId: field for field in definitions}
    supplied: set[str] = set()
    for field in fields:
        definition = available.get(field.type_id)
        if definition is None or field.type_id in supplied:
            raise ScreeningError(f"Unknown or duplicate field typeId: {field.type_id}")
        supplied.add(field.type_id)
        _check_value(
            field=field, definition=definition, countries=countries, nationalities=nationalities
        )
    missing = [
        field.label for field in definitions if field.fieldRequired and field.typeId not in supplied
    ]
    if missing:
        required = ", ".join(missing)
        raise ScreeningError(f"Group requires these fields: {required}. See get_group_settings.")
    return [_wire(field=field) for field in fields]


def _check_value(
    *,
    field: FieldValue,
    definition: FieldDefinition,
    countries: dict[str, str],
    nationalities: dict[str, str],
) -> None:
    if (field.value is None) == (field.date_time_value is None):
        raise ScreeningError(f"Supply exactly one value for {definition.label}.")
    if (definition.fieldValueType == "DATE") != (field.date_time_value is not None):
        raise ScreeningError(f"Use the template's value type for {definition.label}.")
    if field.value is None:
        return
    if definition.fieldValueType == "COUNTRY" and field.value not in countries:
        raise ScreeningError(f"Use an ISO alpha-3 country code for {definition.label}.")
    if definition.fieldValueType == "STATE" and field.value not in nationalities:
        raise ScreeningError(f"Use a passport nationality code for {definition.label}.")
    if definition.fieldValueType == "PASSPORT_DOCUMENT_TYPE" and field.value not in _DOCUMENTS:
        raise ScreeningError(f"Invalid document type for {definition.label}.")
    if definition.fieldValueType == "GENDER" and field.value not in _GENDERS:
        raise ScreeningError(f"Invalid gender for {definition.label}.")


def _wire(*, field: FieldValue) -> dict[str, str]:
    if field.date_time_value is not None:
        return {"typeId": field.type_id, "dateTimeValue": field.date_time_value.isoformat()}
    if field.value is None:
        raise ScreeningError("Supply exactly one value.")
    return {"typeId": field.type_id, "value": field.value}


def _normalized(*, value: str) -> str:
    return to_snake(value).upper().replace(" ", "_")


def _upper(*, value: str | None) -> str | None:
    return None if value is None else value.upper()
