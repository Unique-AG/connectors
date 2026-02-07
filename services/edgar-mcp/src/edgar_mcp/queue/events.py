from typing import Annotated, Literal

from cloudevents.pydantic import CloudEvent
from pydantic import BaseModel, Discriminator, TypeAdapter

EVENT_SOURCE = "/edgar-mcp"

# Ping event

PING_EVENT_TYPE = "com.unique-ag.edgar-mcp.ping"

class PingData(BaseModel):
    """Test event payload used for health checks and connectivity verification."""

    message: str = "pong"


class PingEvent(BaseModel):
    type: Literal[PING_EVENT_TYPE] = PING_EVENT_TYPE
    data: PingData


# Second test event

SECOND_TEST_EVENT_TYPE = "com.unique-ag.edgar-mcp.second-test"

class SecondTestData(BaseModel):
    """Test event payload used for health checks and connectivity verification."""

    which: int = 2

class SecondTestEvent(BaseModel):
    type: Literal[SECOND_TEST_EVENT_TYPE] = SECOND_TEST_EVENT_TYPE
    data: SecondTestData


# To add a new event:
# 1. Define a data model (e.g. SyncFilingData)
# 2. Define an event model with type: Literal[<EVENT_TYPE_CONST>]
# 3. Add it to the EdgarEvent union below

EdgarEvent = Annotated[
    PingEvent | SecondTestEvent,  # | SyncFilingEvent | ...
    Discriminator("type"),
]

_event_adapter: TypeAdapter[EdgarEvent] = TypeAdapter(EdgarEvent)


def create_event(event: EdgarEvent) -> CloudEvent:
    """Wrap a typed event in a CloudEvent envelope for publishing."""
    return CloudEvent(
        type=event.type,
        source=EVENT_SOURCE,
        data=event.data.model_dump(),
    )


def parse_event_data(cloud_event: CloudEvent) -> EdgarEvent:
    """Parse a CloudEvent into a typed EdgarEvent via discriminated union."""
    return _event_adapter.validate_python(
        {"type": cloud_event["type"], "data": cloud_event.data},
    )
