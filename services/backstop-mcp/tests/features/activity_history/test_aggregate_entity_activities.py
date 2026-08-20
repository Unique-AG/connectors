from datetime import date

from backstop_mcp.features.activity_history import (
    ActivityRegardingDto,
    ActivityTagChipDto,
    EntityActivityDto,
    aggregate_entity_activities,
)


def _row(
    row_id: str,
    *,
    type: str | None = "Meeting",
    tags: tuple[ActivityTagChipDto, ...] = (),
    associated_with: tuple[ActivityRegardingDto, ...] = (),
    effective_date: date | None = date(2026, 8, 3),
) -> EntityActivityDto:
    return EntityActivityDto(
        id=row_id,
        type=type,
        tags=tags,
        associated_with=associated_with,
        effective_date=effective_date,
    )


class TestAggregateEntityActivities:
    def test_groups_by_type(self) -> None:
        buckets = aggregate_entity_activities(
            (_row("1"), _row("2", type="Call"), _row("3")),
            group_by="type",
        )

        assert [(bucket.key, bucket.count) for bucket in buckets] == [
            ("Meeting", 2),
            ("Call", 1),
        ]

    def test_tag_or_counts_each_tag(self) -> None:
        buckets = aggregate_entity_activities(
            (
                _row(
                    "1",
                    tags=(
                        ActivityTagChipDto(id="a", name="A"),
                        ActivityTagChipDto(id="b", name="B"),
                    ),
                ),
                _row("2", tags=(ActivityTagChipDto(id="a", name="A"),)),
                _row("3"),
            ),
            group_by="tag",
        )

        by_key = {bucket.key: bucket.count for bucket in buckets}
        assert by_key == {"a": 2, "b": 1, "(untagged)": 1}

    def test_period_uses_year_month(self) -> None:
        buckets = aggregate_entity_activities(
            (
                _row("1", effective_date=date(2026, 8, 3)),
                _row("2", effective_date=date(2026, 8, 20)),
                _row("3", effective_date=None),
            ),
            group_by="period",
        )

        by_key = {bucket.key: bucket.count for bucket in buckets}
        assert by_key == {"2026-08": 2, "(undated)": 1}

    def test_party_counts_each_associated_with(self) -> None:
        buckets = aggregate_entity_activities(
            (
                _row(
                    "1",
                    associated_with=(
                        ActivityRegardingDto(id="a", resource_type="organizations"),
                        ActivityRegardingDto(id="b", resource_type="people"),
                    ),
                ),
                _row(
                    "2",
                    associated_with=(ActivityRegardingDto(id="a", resource_type="organizations"),),
                ),
                _row("3"),
            ),
            group_by="party",
        )

        by_key = {bucket.key: (bucket.label, bucket.count) for bucket in buckets}
        assert by_key == {
            "a": ("organizations:a", 2),
            "b": ("people:b", 1),
            "(unattributed)": ("(unattributed)", 1),
        }
