"""Harness self-test against `selftest/server.py`. State lives in the server process, so the
leftover check runs inside the same session as the scenario."""

import sys
from pathlib import Path

from mcp import StdioServerParameters

from probe import Leftover, Probe, Target

TARGET = Target(
    name="selftest",
    stdio=StdioServerParameters(
        command=sys.executable, args=[str(Path(__file__).parent.parent / "selftest/server.py")]
    ),
)


async def scenario(probe: Probe) -> None:
    name = probe.name("thing")
    await probe.call("create_thing", {"name": name})
    probe.on_cleanup(name, lambda: _delete(probe, name))
    await probe.call("delete_thing", {"name": name})


async def _delete(probe: Probe, name: str) -> None:
    outcome = await probe.call("delete_thing", {"name": name})
    assert outcome.text == f"deleted {name}", outcome.text


async def find_leftovers(probe: Probe, prefix: str) -> list[Leftover]:
    names = (await probe.call("list_things", {})).json_body() or []
    names = names.get("result", names) if isinstance(names, dict) else names
    return [Leftover(kind="thing", id=n, title=n) for n in names if n.startswith(prefix)]


async def delete_leftover(probe: Probe, leftover: Leftover) -> None:
    await _delete(probe, leftover.id)
