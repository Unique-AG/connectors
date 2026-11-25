from typing import ClassVar
from typing import Literal
from typing import TypeIs

from fastmcp.exceptions import ToolError
from mcp.types import InputRequiredResult
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class Option(BaseModel):
    """One thing a person or the model can pick."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    ref: str = Field(
        description=(
            "Identifies this option. To pick it, call the tool again with this value exactly as "
            "given here. Never invent one."
        )
    )
    label: str = Field(description="What the option is, as the person was shown it.")


class Confirmed(BaseModel):
    """The tool may go ahead."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    skipped: bool = Field(
        description="True when the client said no person has to confirm this call."
    )


class NotConfirmed(BaseModel):
    """The tool must not go ahead."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    reason: Literal["declined", "unavailable"] = Field(
        description=(
            "declined: the person said no, did not answer in time, or gave no usable answer. "
            "unavailable: this client cannot ask a person."
        )
    )
    message: str = Field(description="What happened, and what to tell the user.")


class NotConfirmedError(ToolError):
    """What `Elicitation.confirm` raises when the tool must not go ahead."""

    def __init__(self, result: NotConfirmed) -> None:
        super().__init__(result.message)
        self.result: NotConfirmed = result


class ChosenOne(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    status: Literal["chosen"] = "chosen"
    ref: str


class ChosenMany(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    status: Literal["chosen"] = "chosen"
    refs: tuple[str, ...]


class NeedsChoice(BaseModel):
    """Nobody picked, so the model has to: the options it may pick from."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    status: Literal["needs_choice"] = Field(
        default="needs_choice",
        description="Always needs_choice: nothing was done yet.",
    )
    question: str = Field(description="The question the person would have been asked.")
    options: tuple[Option, ...] = Field(
        description=(
            "What may be picked. Ask the user which they mean unless the conversation already "
            "says so, then call the tool again with the ref of each one picked."
        )
    )
    multiple: bool = Field(description="True when several options may be picked in one call.")
    min_items: int = Field(description="The fewest options one call may pick.")
    max_items: int | None = Field(
        description="The most options one call may pick, or null when there is no limit."
    )
    reason: Literal["skipped", "unavailable", "declined", "timed_out"] = Field(
        description=(
            "Why nobody picked. skipped: the client said not to ask. unavailable: this client "
            "cannot ask a person. declined: the person said no or gave no usable answer. "
            "timed_out: the person did not answer in time."
        )
    )


def needs_answer(result: object) -> TypeIs[InputRequiredResult | NeedsChoice]:
    """True when the tool has to return `result` now, before doing anything.

    An `InputRequiredResult` goes to the client, which shows the person a form and calls the tool
    again with the answer. A `NeedsChoice` goes to the model, which picks and calls again.
    """
    return isinstance(result, InputRequiredResult | NeedsChoice)
