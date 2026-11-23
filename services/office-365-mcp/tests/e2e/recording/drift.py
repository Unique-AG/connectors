"""Records a scenario again in memory, scrubs it, and compares each file with the stored one, byte
for byte (the metadata file without its record time and SDK versions). Prints a diff of the
scrubbed files, which hold no raw value. Exit 0 when equal, 1 on drift, 2 when refused.

  GRAPH_TOKEN=... SEED_UPNS=... python -m tests.e2e.recording.drift uc-02-01 --target graph
"""

import argparse
import asyncio
import difflib
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import tests.e2e.test_scenarios as runner
from tests.e2e.recording import stand_in as stand_in_graph
from tests.e2e.recording.guard import DEFAULT_CAP, Refused
from tests.e2e.recording.record import STAND_IN_OUT, record, resolve, upns_from_environment
from tests.e2e.recording.scrub import Target, files_of
from tests.e2e.recording.stand_in import StandIn

_VOLATILE = re.compile(r"^recorded_at: .*\n|^sdk_versions:\n(?:  .*\n)*", re.M)
_SHOWN = 40


def stored(fixture: str, out: Path) -> dict[str, bytes]:
    names = [out / "fixtures" / f"{fixture}.json", out / "fixtures" / f"{fixture}.meta.yaml"]
    names += sorted((out / "bodies").glob(f"{fixture}.[0-9][0-9].*"))
    return {str(p.relative_to(out)): p.read_bytes() for p in names if p.is_file()}


def _comparable(name: str, body: bytes) -> bytes:
    return _VOLATILE.sub("", body.decode()).encode() if name.endswith(".meta.yaml") else body


def differences(before: Mapping[str, bytes], now: Mapping[str, bytes]) -> list[str]:
    found: list[str] = []
    for name in sorted(before.keys() | now.keys()):
        if name not in now:
            found.append(f"{name}: stored, not recorded now")
        elif name not in before:
            found.append(f"{name}: recorded now, not stored")
        elif (old := _comparable(name, before[name])) != (new := _comparable(name, now[name])):
            if name.endswith((".json", ".yaml")):
                lines = difflib.unified_diff(
                    old.decode().splitlines(), new.decode().splitlines(), name, name, lineterm=""
                )
                found += list(lines)[:_SHOWN]
            else:
                found.append(f"{name}: the bytes differ")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("scenarios", nargs="+")
    parser.add_argument("--target", choices=["graph", "stand-in"], required=True)
    parser.add_argument("--allow-writes", action="store_true")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stand-in-variant", action="append", default=[])
    arguments = parser.parse_args(argv)
    scenarios, variants = (
        cast("list[str]", arguments.scenarios),
        cast("list[str]", arguments.stand_in_variant),
    )
    allow_writes = cast("bool", arguments.allow_writes)
    target = cast("Target", arguments.target)
    in_memory = target == "stand-in"
    out = cast("Path | None", arguments.out) or (STAND_IN_OUT if in_memory else runner.HERE)
    drifted = 0
    try:
        upns = stand_in_graph.UPNS if in_memory else upns_from_environment()
        token = stand_in_graph.TOKEN if in_memory else os.environ.get("GRAPH_TOKEN", "").strip()
        if not token:
            raise Refused("GRAPH_TOKEN is not set (see tests/e2e/recording/README.md)")
        for scenario in scenarios:
            plan = resolve(scenario)
            graph = StandIn(frozenset(variants)) if in_memory else None
            outcome = asyncio.run(
                record(
                    plan,
                    target,
                    token=token,
                    upns=upns,
                    allow_writes=allow_writes,
                    cap=DEFAULT_CAP,
                    stand_in=graph,
                )
            )
            found = differences(stored(plan.fixture, out), files_of(outcome.fixture))
            drifted += bool(found)
            print(f"{scenario}: " + ("DRIFT\n" + "\n".join(found) if found else "no drift"))
    except Refused as refused:
        print(f"refused: {str(refused).splitlines()[0]}", file=sys.stderr)
        return 2
    return 1 if drifted else 0


if __name__ == "__main__":
    sys.exit(main())
