from collections.abc import Callable, Sequence
from datetime import date

from backstop_mcp.features.data_hygiene.employment import (
    EmploymentIndex,
    build_organization_employment_index,
    build_person_employment_index,
)
from backstop_mcp.features.data_hygiene.types import (
    EmploymentRules,
    TypeVocabulary,
)


class EmploymentIndexFactory:
    """Owns the employment vocabulary and the clock; builds an `EmploymentIndex` per document.

    The employment vocabulary is a constructor dependency and the relationship-type names arrive
    side-loaded on the caller's own GET, so building an index needs no client, no cache and no
    lock: it is synchronous, and every caller gets the same index for the same record.

    Built by `create_employment_index_factory` in `create_app()` and reached via
    `runtime.get_employment_index_factory()`.
    """

    def __init__(
        self,
        *,
        rules: EmploymentRules,
        clock: Callable[[], date] = date.today,
    ) -> None:
        self._rules: EmploymentRules = rules
        self._clock: Callable[[], date] = clock

    @property
    def rules(self) -> EmploymentRules:
        """The vocabulary this factory was built with. Read-only; set once at composition."""
        return self._rules

    def index_for_person(
        self,
        *,
        relationships: list[dict[str, object]],
        relationship_types: list[dict[str, object]],
    ) -> EmploymentIndex:
        """The `EmploymentIndex` for `entityRelationships` side-loaded off a person's own GET.

        Both arguments are side-loaded from the person's own GET — no second fetch of the person
        and no per-relationship fetch of its type. Keyword-only because the two are the same type
        and transposing them would silently misclassify every relationship.
        """
        return build_person_employment_index(
            relationships=relationships,
            relationship_types=relationship_types,
            rules=self._rules,
            today=self._clock(),
        )

    def index_for_organization(
        self,
        *,
        relationships: list[dict[str, object]],
        relationship_types: list[dict[str, object]],
    ) -> EmploymentIndex:
        """The `EmploymentIndex` for `entityRelationships` side-loaded off an organization's own
        GET. Mirrors `index_for_person`; see there for why both arguments are keyword-only.
        """
        return build_organization_employment_index(
            relationships=relationships,
            relationship_types=relationship_types,
            rules=self._rules,
            today=self._clock(),
        )


def create_employment_index_factory(
    *,
    employment_type_ids: Sequence[str],
    employment_type_markers: Sequence[str],
    former_type_ids: Sequence[str],
    former_type_markers: Sequence[str],
) -> EmploymentIndexFactory:
    """Build the factory from configured values, translating them into the feature's own type."""
    return EmploymentIndexFactory(
        rules=EmploymentRules(
            employment=TypeVocabulary(
                type_ids=frozenset(employment_type_ids),
                name_markers=frozenset(employment_type_markers),
            ),
            former=TypeVocabulary(
                type_ids=frozenset(former_type_ids),
                name_markers=frozenset(former_type_markers),
            ),
        ),
    )
