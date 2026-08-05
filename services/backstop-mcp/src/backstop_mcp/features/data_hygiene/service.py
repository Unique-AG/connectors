from collections.abc import Callable, Sequence
from datetime import date

from backstop_mcp.features.data_hygiene.departed import detect_departed_employment
from backstop_mcp.features.data_hygiene.types import (
    DepartedEmployment,
    DepartureRules,
    TypeVocabulary,
)


class DepartedContactDetector:
    """Answers one question — has this person's employment ended? — and owns what that needs.

    The employment vocabulary is a constructor dependency and the relationship-type names arrive
    side-loaded on the caller's own GET, so `verify` needs no client, no cache and no lock: it is
    synchronous, and every caller gets the same verdict for the same record.

    Built by `create_departed_contact_detector` in `create_app()` and reached via
    `runtime.get_departed_contact_detector()`.
    """

    def __init__(
        self,
        *,
        rules: DepartureRules,
        clock: Callable[[], date] = date.today,
    ) -> None:
        self._rules: DepartureRules = rules
        self._clock: Callable[[], date] = clock

    @property
    def rules(self) -> DepartureRules:
        """The vocabulary this detector was built with. Read-only; set once at composition."""
        return self._rules

    def verify(
        self,
        *,
        relationships: list[dict[str, object]],
        relationship_types: list[dict[str, object]],
    ) -> DepartedEmployment | None:
        """The departed-employment signal for one person, or None when they are current.

        Both arguments are side-loaded from the person's own GET — no second fetch of the person
        and no per-relationship fetch of its type. Keyword-only because the two are the same type
        and transposing them would silently report every person as current.
        """
        return detect_departed_employment(
            relationships=relationships,
            relationship_types=relationship_types,
            rules=self._rules,
            today=self._clock(),
        )


def create_departed_contact_detector(
    *,
    employment_type_ids: Sequence[str],
    employment_type_markers: Sequence[str],
    former_type_ids: Sequence[str],
    former_type_markers: Sequence[str],
) -> DepartedContactDetector:
    """Build the detector from configured values, translating them into the feature's own type."""
    return DepartedContactDetector(
        rules=DepartureRules(
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
