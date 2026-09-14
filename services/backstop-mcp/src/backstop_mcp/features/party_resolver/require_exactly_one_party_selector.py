"""Blank→None, exactly one of `party_id`/`search`, and `/` rejected in path-segment ids."""


def blank_to_none(value: object) -> object:
    if isinstance(value, str) and not value.strip():
        return None
    return value


def require_path_segment(value: str, *, field_name: str) -> None:
    if "/" in value:
        raise ValueError(f"{field_name} {value!r} must not contain '/'")


def require_exactly_one_party_selector(*, party_id: str | None, search: str | None) -> None:
    if (party_id is None) == (search is None):
        raise ValueError("Exactly one of party_id or search must be provided")
    if party_id is not None:
        require_path_segment(party_id, field_name="party_id")
