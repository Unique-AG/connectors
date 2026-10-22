#!/usr/bin/env python3
"""render-use-cases.py — render the reader's page of use cases from the Gherkin features.

Usage:
  scripts/render-use-cases.py [--check]

  --check  Verify that docs/use-cases.md matches what would be generated. Exits 1 on drift
           (suitable for CI).

The script owns the text between the two markers in docs/use-cases.md. A person owns the rest of
the page. The features in features/ are the only source of the examples.

Requirements:
  - the service's own virtualenv, because this imports `gherkin` (`uv run python …`)
"""

import argparse
import difflib
import functools
import pathlib
import re
import sys
from collections.abc import Mapping, Sequence
from typing import cast

import yaml
from gherkin.parser import Parser

_INVOCATION = "scripts/render-use-cases.py"
_ROOT = pathlib.Path(__file__).resolve().parents[1]
_FEATURES = _ROOT / "features"

TARGET = _ROOT / "docs" / "use-cases.md"

_BEGIN = "<!-- use-cases:begin -->"
_END = "<!-- use-cases:end -->"

_AREAS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Mail",
        (
            "02-find-and-read-mail",
            "04-draft-and-send-mail",
            "05-organize-the-mailbox",
            "11-mailbox-preferences",
        ),
    ),
    ("Files in OneDrive and SharePoint", ("01-find-and-read-files", "10-organize-and-share-files")),
    (
        "Microsoft Teams",
        (
            "06-catch-up-on-teams",
            "09-post-in-teams",
            "13-run-teams-chats-and-online-meetings",
        ),
    ),
    (
        "Calendar",
        (
            "03-read-the-calendar",
            "07-schedule-and-answer-meetings",
            "14-share-and-delegate-calendars",
        ),
    ),
    ("Notes in OneNote", ("08-work-with-notes",)),
    ("Contacts", ("12-manage-contacts",)),
    ("Across mail, calendar, and files", ("15-work-across-mail-calendar-and-files",)),
)


def _object(value: object) -> Mapping[str, object]:
    assert isinstance(value, Mapping), f"expected a mapping, got {type(value).__name__}"
    return cast("Mapping[str, object]", value)


def _list(value: object) -> Sequence[object]:
    assert isinstance(value, list), f"expected a list, got {type(value).__name__}"
    return cast("Sequence[object]", value)


def _paragraph(description: object) -> str:
    return " ".join(line.strip() for line in str(description).splitlines() if line.strip())


def _step_text(step: Mapping[str, object]) -> str:
    return re.sub(r"<(\w+)>", r"`<\1>`", str(step["text"]))


@functools.cache
def _statuses() -> dict[str, str]:
    return {
        scenario_id: str(_object(entry)["status"])
        for sidecar in _FEATURES.glob("*.calls.yaml")
        for scenario_id, entry in _object(yaml.safe_load(sidecar.read_text())).items()
    }


def _is_gap(scenario: Mapping[str, object]) -> bool:
    scenario_id = next(
        str(_object(tag)["name"])[1:]
        for tag in _list(scenario["tags"])
        if str(_object(tag)["name"]).startswith("@uc-")
    )
    return _statuses()[scenario_id] == "gap"


def _scenario(scenario: Mapping[str, object]) -> list[str]:
    lines = [f"**{scenario['name']}**", ""]
    lines += [
        f"- **{str(_object(step)['keyword']).strip()}** {_step_text(_object(step))}"
        for step in _list(scenario["steps"])
    ]
    for examples in map(_object, _list(scenario["examples"])):
        header = [
            str(_object(cell)["value"]) for cell in _list(_object(examples["tableHeader"])["cells"])
        ]
        lines += [
            "",
            "| " + " | ".join(header) + " |",
            "| " + " | ".join("---" for _ in header) + " |",
        ]
        for row in map(_object, _list(examples["tableBody"])):
            cells = [str(_object(cell)["value"]) for cell in _list(row["cells"])]
            lines.append("| " + " | ".join(cells) + " |")
    return [*lines, ""]


def _rule(rule: Mapping[str, object], gaps: list[str]) -> list[str]:
    scenarios: list[Mapping[str, object]] = []
    for child in map(_object, _list(rule["children"])):
        if "scenario" not in child:
            continue
        scenario = _object(child["scenario"])
        if _is_gap(scenario):
            gaps.append(str(scenario["name"]))
        else:
            scenarios.append(scenario)
    if not scenarios:
        return []
    lines = [f"#### {rule['name']}", ""]
    if description := _paragraph(rule["description"]):
        lines += [description, ""]
    for scenario in scenarios:
        lines += _scenario(scenario)
    return lines


def _feature(stem: str) -> list[str]:
    document = _object(Parser().parse((_FEATURES / f"{stem}.feature").read_text()))
    feature = _object(document["feature"])
    lines = [f"### {feature['name']}", ""]
    if description := _paragraph(feature["description"]):
        lines += [description, ""]
    children = [_object(child) for child in _list(feature["children"])]
    for child in children:
        if "background" in child:
            steps = [
                str(_object(step)["text"]) for step in _list(_object(child["background"])["steps"])
            ]
            lines += [f"**Starting point.** {'; '.join(steps)}.", ""]
    gaps: list[str] = []
    for child in children:
        if "rule" in child:
            lines += _rule(_object(child["rule"]), gaps)
    if gaps:
        lines += ["#### Not supported yet", ""] + [f"- {name}" for name in gaps] + [""]
    return lines


def _generated() -> str:
    covered = [stem for _, stems in _AREAS for stem in stems]
    on_disk = sorted(path.stem for path in _FEATURES.glob("*.feature"))
    assert sorted(covered) == on_disk, (
        f"every feature file belongs to exactly one area in {_INVOCATION}: "
        f"missing {sorted(set(on_disk) - set(covered))}, "
        f"unknown {sorted(set(covered) - set(on_disk))}"
    )
    lines: list[str] = []
    for area, stems in _AREAS:
        lines += [f"## {area}", ""]
        for stem in stems:
            lines += _feature(stem)
    return "\n".join(lines).rstrip("\n") + "\n"


def render() -> str:
    current = TARGET.read_text()
    assert _BEGIN in current and _END in current, (
        f"{TARGET.name} needs the markers {_BEGIN} and {_END} around the generated text"
    )
    head = current.partition(_BEGIN)[0]
    tail = current.partition(_END)[2]
    return f"{head}{_BEGIN}\n\n{_generated()}\n{_END}{tail}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed page matches what would be generated; exit 1 on drift",
    )
    args = parser.parse_args(argv)

    expected = render()
    if not cast("bool", args.check):
        TARGET.write_text(expected)
        print(f"wrote {TARGET.relative_to(_ROOT)}")
        return 0

    committed = TARGET.read_text()
    if committed == expected:
        return 0
    sys.stderr.writelines(
        difflib.unified_diff(
            committed.splitlines(keepends=True),
            expected.splitlines(keepends=True),
            fromfile=str(TARGET.relative_to(_ROOT)),
            tofile="generated",
        )
    )
    sys.stderr.write(f"\n{TARGET.name} is stale. Run {_INVOCATION} and commit the result.\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
