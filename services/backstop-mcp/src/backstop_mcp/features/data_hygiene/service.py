from collections.abc import Callable, Sequence
from datetime import date

from backstop_mcp.backstop_client import BackstopApiResource
from backstop_mcp.features.data_hygiene.api_responses import (
    EntityRelationshipAttributes,
    RelationshipTypeAttributes,
)
from backstop_mcp.features.data_hygiene.employment import EmploymentIndex, build_employment_index
from backstop_mcp.features.data_hygiene.internal_dto import (
    EmploymentRulesDto,
    TypeVocabularyDto,
)

type RelationshipResource = BackstopApiResource[EntityRelationshipAttributes]
type RelationshipTypeResource = BackstopApiResource[RelationshipTypeAttributes]


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
        rules: EmploymentRulesDto,
        clock: Callable[[], date] = date.today,
    ) -> None:
        self._rules: EmploymentRulesDto = rules
        self._clock: Callable[[], date] = clock

    @property
    def rules(self) -> EmploymentRulesDto:
        """The vocabulary this factory was built with. Read-only; set once at composition."""
        return self._rules

    def index(
        self,
        *,
        relationships: list[RelationshipResource],
        relationship_types: list[RelationshipTypeResource],
    ) -> EmploymentIndex:
        """Build an `EmploymentIndex` from `entityRelationships` side-loaded off a person or
        organization GET.

        Both arguments come from that GET's includes — no second fetch of the subject and no
        per-relationship fetch of its type. Keyword-only because the two lists share a resource
        shape and transposing them would silently misclassify every relationship.
        """
        return build_employment_index(
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
        rules=EmploymentRulesDto(
            employment=TypeVocabularyDto(
                type_ids=frozenset(employment_type_ids),
                name_markers=frozenset(employment_type_markers),
            ),
            former=TypeVocabularyDto(
                type_ids=frozenset(former_type_ids),
                name_markers=frozenset(former_type_markers),
            ),
        ),
    )
