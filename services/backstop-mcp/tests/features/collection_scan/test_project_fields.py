from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.features.collection_scan import project_fields
from backstop_mcp.models import OmitNoneModel


class _ChipDto(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    name: str | None = None


class _RowDto(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    title: str | None = None
    body: str | None = None
    chip: _ChipDto | None = None
    labels: tuple[str, ...] = ()
    not_published: str = "internal"


class _ChipResponse(OmitNoneModel):
    id: str = Field(description="Chip id.")
    name: str | None = Field(default=None, description="Chip name.")


class _RowResponse(OmitNoneModel):
    id: str | None = Field(default=None, description="Row id.")
    title: str | None = Field(default=None, description="Row title.")
    body: str | None = Field(default=None, description="Row body.")
    chip: _ChipResponse | None = Field(default=None, description="Nested chip.")
    labels: tuple[str, ...] | None = Field(default=None, description="Row labels.")


def _row() -> _RowDto:
    return _RowDto(
        id="7",
        title="Quarterly Review",
        body="<p>raw</p>",
        chip=_ChipDto(id="c1", name="Capstone"),
        labels=("a", "b"),
    )


class TestProjectFields:
    def test_unselected_fields_are_left_at_their_default(self) -> None:
        projected = project_fields(_row(), fields={"id", "title"}, into=_RowResponse)

        assert projected.id == "7"
        assert projected.title == "Quarterly Review"
        assert projected.body is None
        assert projected.chip is None
        assert projected.labels is None

    def test_a_nested_dto_becomes_its_nested_response(self) -> None:
        projected = project_fields(_row(), fields={"chip"}, into=_RowResponse)

        assert projected.chip is not None
        assert projected.chip.id == "c1"
        assert projected.chip.name == "Capstone"

    def test_a_tuple_field_survives_as_a_tuple(self) -> None:
        projected = project_fields(_row(), fields={"labels"}, into=_RowResponse)

        assert projected.labels == ("a", "b")

    def test_an_override_replaces_the_stored_value(self) -> None:
        projected = project_fields(
            _row(), fields={"body"}, into=_RowResponse, overrides={"body": "raw"}
        )

        assert projected.body == "raw"

    def test_an_override_for_an_unselected_field_is_not_applied(self) -> None:
        projected = project_fields(
            _row(), fields={"id"}, into=_RowResponse, overrides={"body": "raw"}
        )

        assert projected.body is None

    def test_a_selection_naming_something_unpublished_is_ignored(self) -> None:
        """The response model, not the selection, decides which keys exist."""
        projected = project_fields(_row(), fields={"id", "not_published"}, into=_RowResponse)

        assert projected.id == "7"
        assert "not_published" not in projected.model_dump()
