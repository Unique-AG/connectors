import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.e2e.recording import stand_in
from tests.e2e.recording.record import Outcome, Plan, record, resolve, write
from tests.e2e.recording.stand_in import StandIn

SCENARIOS = ("uc-02-01", "uc-05-16", "uc-01-06")


@dataclass(frozen=True)
class Recorded:
    out: Path
    outcomes: dict[str, Outcome]


def record_on(
    plan: Plan | str,
    graph: StandIn | None = None,
    *,
    allow_writes: bool = True,
    upns: tuple[str, ...] = stand_in.UPNS,
) -> Outcome:
    chosen = resolve(plan) if isinstance(plan, str) else plan
    graph = graph or StandIn()
    return asyncio.run(
        record(
            chosen,
            "stand-in",
            token=stand_in.TOKEN,
            upns=upns,
            allow_writes=allow_writes,
            stand_in=graph,
        )
    )


@pytest.fixture(scope="session")
def recorded(tmp_path_factory: pytest.TempPathFactory) -> Recorded:
    out = tmp_path_factory.mktemp("recorded")
    outcomes = {scenario: record_on(scenario) for scenario in SCENARIOS}
    for outcome in outcomes.values():
        _ = write(outcome.cassette, out)
    return Recorded(out, outcomes)
