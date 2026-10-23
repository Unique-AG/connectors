#!/usr/bin/env python3
"""render-use-cases.py — render the guide and the status page from the features and sidecars.

Usage:
  scripts/render-use-cases.py [--check]

  --check  Verify that docs/use-cases.md and features/STATUS.md match what would be generated.
           Exits 1 on drift (suitable for CI).

The script owns the text between the two markers in docs/use-cases.md, and all of
features/STATUS.md. A person owns the rest of the guide. The features and the sidecars in
features/ are the only source of the examples, the prompts, the limits, and the status.

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
from dataclasses import dataclass
from typing import cast

import yaml
from gherkin.parser import Parser

from office_365_mcp.tools import TOOL_NAMES

_INVOCATION = "scripts/render-use-cases.py"
_ROOT = pathlib.Path(__file__).resolve().parents[1]
_FEATURES = _ROOT / "features"

TARGET = _ROOT / "docs" / "use-cases.md"
STATUS = _FEATURES / "STATUS.md"

_BEGIN = "<!-- use-cases:begin -->"
_END = "<!-- use-cases:end -->"

_SURFACES = ("Outlook", "Teams", "SharePoint", "OneNote", "Across sources")
_AREA_TAGS = {
    "@outlook-mail": ("Outlook", 0),
    "@outlook-calendar": ("Outlook", 1),
    "@outlook-contacts": ("Outlook", 2),
    "@teams": ("Teams", 0),
    "@sharepoint": ("SharePoint", 0),
    "@onenote": ("OneNote", 0),
}
_STATUSES = ("working", "partly", "gap", "untested")
_KINDS = ("tool", "parameter", "description", "preset", "graph", "unknown")
_FIXABLE = _KINDS[:4]
_KIND_TITLES = {
    "tool": "A tool is missing",
    "parameter": "A parameter is missing",
    "description": "A description steers the assistant away",
    "preset": "The tools sit in different presets",
    "graph": "Microsoft Graph cannot do it",
    "unknown": "It fails in prod and the cause is not known",
}


@dataclass(frozen=True)
class _Feature:
    stem: str
    node: Mapping[str, object]
    surface: str
    area: int


def _object(value: object) -> Mapping[str, object]:
    assert isinstance(value, Mapping), f"expected a mapping, got {type(value).__name__}"
    return cast("Mapping[str, object]", value)


def _list(value: object) -> Sequence[object]:
    assert isinstance(value, list), f"expected a list, got {type(value).__name__}"
    return cast("Sequence[object]", value)


def _paragraph(description: object) -> str:
    return " ".join(line.strip() for line in str(description).splitlines() if line.strip())


def _sentence(text: str) -> str:
    text = re.sub(r"<([^<>]+)>", r"`<\1>`", text).strip().rstrip(".")
    return f"{text[:1].upper()}{text[1:]}."


@functools.cache
def _entries() -> dict[str, Mapping[str, object]]:
    return {
        scenario_id: _object(entry)
        for sidecar in sorted(_FEATURES.glob("*.calls.yaml"))
        for scenario_id, entry in _object(
            cast("object", yaml.safe_load(sidecar.read_text()))
        ).items()
    }


@functools.cache
def _features() -> tuple[_Feature, ...]:
    found: list[_Feature] = []
    for path in _FEATURES.glob("*.feature"):
        feature = _object(_object(Parser().parse(path.read_text()))["feature"])
        names = {str(_object(tag)["name"]) for tag in _list(feature["tags"])}
        areas = {_AREA_TAGS[name] for name in names if name in _AREA_TAGS}
        assert areas, f"{path.name} needs an area tag from {sorted(_AREA_TAGS)}"
        across = len({surface for surface, _ in areas}) > 1
        surface, area = ("Across sources", 0) if across else min(areas)
        found.append(_Feature(path.stem, feature, surface, area))
    return tuple(sorted(found, key=lambda f: (_SURFACES.index(f.surface), f.area, f.stem)))


def _scenario_id(scenario: Mapping[str, object]) -> str:
    return next(
        str(_object(tag)["name"])[1:]
        for tag in _list(scenario["tags"])
        if str(_object(tag)["name"]).startswith("@uc-")
    )


def _blocker(entry: Mapping[str, object]) -> Mapping[str, object]:
    return _object(entry["blocker"])


def _outline_rows(scenario: Mapping[str, object]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for examples in map(_object, _list(scenario["examples"])):
        header = [
            str(_object(cell)["value"]) for cell in _list(_object(examples["tableHeader"])["cells"])
        ]
        for row in map(_object, _list(examples["tableBody"])):
            cells = [str(_object(cell)["value"]) for cell in _list(row["cells"])]
            rows.append(dict(zip(header, cells, strict=True)))
    return rows


def _filled(text: str, row: Mapping[str, str]) -> str:
    return re.sub(r"<([^<>]+)>", lambda match: row[match.group(1)], text)


def _scenario(scenario: Mapping[str, object], entry: Mapping[str, object]) -> list[str]:
    context: list[str] = []
    outcome: list[str] = []
    bucket: list[str] = []
    for step in map(_object, _list(scenario["steps"])):
        kind = str(step["keywordType"])
        if kind != "Conjunction":
            bucket = context if kind == "Context" else outcome if kind == "Outcome" else []
        bucket.append(str(step["text"]))
    lines = [f"**{scenario['name']}**", "", f'Ask your assistant: "{entry["ask"]}"', ""]
    if entry["status"] == "partly":
        lines += ['!!! warning "Limit"', f"    {_blocker(entry)['user']}", ""]
    if rows := _outline_rows(scenario):
        lines += ["Cases:", ""]
        lines += [
            "- " + " ".join(_sentence(_filled(text, row)) for text in [*context, *outcome])
            for row in rows
        ]
        return [*lines, ""]
    if context:
        lines += [f"Situation: {' '.join(_sentence(text) for text in context)}", ""]
    lines += ["What happens:", ""] + [f"- {_sentence(text)}" for text in outcome]
    if entry["asks_user"] and not any("approve" in text for text in outcome):
        lines += ["- The assistant asks Mia to approve first."]
    return [*lines, ""]


def _slug(heading: str) -> str:
    return re.sub(r"[^a-z0-9 -]", "", heading.lower()).replace(" ", "-")


def _feature(feature: _Feature) -> list[str]:
    node = feature.node
    lines = [f"### {node['name']}", ""]
    if description := _paragraph(node["description"]):
        lines += [description, ""]
    children = [_object(child) for child in _list(node["children"])]
    for child in children:
        if "background" in child:
            steps = [
                str(_object(step)["text"]) for step in _list(_object(child["background"])["steps"])
            ]
            lines += [f"**Starting point.** {'; '.join(steps)}.", ""]
    gaps: list[str] = []
    for rule in (_object(child["rule"]) for child in children if "rule" in child):
        titles: list[str] = []
        shown: list[str] = []
        for scenario in (
            _object(c["scenario"]) for c in map(_object, _list(rule["children"])) if "scenario" in c
        ):
            entry = _entries()[_scenario_id(scenario)]
            if entry["status"] == "gap":
                gaps.append(f"- {_blocker(entry)['user']}")
            else:
                titles.append(str(scenario["name"]))
                shown += _scenario(scenario, entry)
        if shown:
            if titles != [str(rule["name"])]:
                lines += [f"#### {rule['name']}", ""]
            if description := _paragraph(rule["description"]):
                lines += [description, ""]
            lines += shown
    if gaps:
        lines += [f"#### Not supported yet in {str(node['name']).lower()}", "", *gaps, ""]
    return lines


def _contents() -> list[str]:
    lines = ["**On this page**", ""]
    for surface in _SURFACES:
        links = [
            f"[{feature.node['name']}](#{_slug(str(feature.node['name']))})"
            for feature in _features()
            if feature.surface == surface
        ]
        if links:
            lines.append(f"- {surface}: {', '.join(links)}")
    return [*lines, ""]


def _generated() -> str:
    lines = _contents()
    for surface in _SURFACES:
        members = [feature for feature in _features() if feature.surface == surface]
        if members:
            lines += [f"## {surface}", ""]
        for feature in members:
            lines += _feature(feature)
    return "\n".join(lines).rstrip("\n") + "\n"


def render() -> str:
    current = TARGET.read_text()
    assert _BEGIN in current and _END in current, (
        f"{TARGET.name} needs the markers {_BEGIN} and {_END} around the generated text"
    )
    head = current.partition(_BEGIN)[0]
    tail = current.partition(_END)[2]
    return f"{head}{_BEGIN}\n\n{_generated()}\n{_END}{tail}"


def _names() -> dict[str, tuple[str, str, str, str]]:
    names: dict[str, tuple[str, str, str, str]] = {}
    for feature in _features():
        for rule in (
            _object(c["rule"]) for c in map(_object, _list(feature.node["children"])) if "rule" in c
        ):
            for scenario in (
                _object(c["scenario"])
                for c in map(_object, _list(rule["children"]))
                if "scenario" in c
            ):
                names[_scenario_id(scenario)] = (
                    feature.surface,
                    str(feature.node["name"]),
                    str(scenario["name"]),
                    "unhappy"
                    if any(_object(tag)["name"] == "@unhappy" for tag in _list(scenario["tags"]))
                    else "happy",
                )
    return names


def _blocker_table(kind: str, names: Mapping[str, tuple[str, str, str, str]]) -> list[str]:
    rows: list[str] = []
    for scenario_id, entry in _entries().items():
        if entry["status"] in ("partly", "gap") and _blocker(entry)["kind"] == kind:
            blocker = _blocker(entry)
            tool = f"`{blocker['tool']}`" if "tool" in blocker else ""
            _, feature, scenario, _ = names[scenario_id]
            rows.append(
                f"| `{scenario_id}` | {feature} | {scenario} | {entry['status']} | "
                + f"{tool} | {blocker['text']} |"
            )
    if not rows:
        return []
    head = [
        "| Id | Feature | Scenario | Status | Tool | Cause |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    return [f"### {_KIND_TITLES[kind]} ({len(rows)})", "", *head, *rows, ""]


def exceptions() -> dict[str, Mapping[str, object]]:
    path = _FEATURES / "coverage-exceptions.yaml"
    return {
        str(tool): _object(entry)
        for tool, entry in _object(cast("object", yaml.safe_load(path.read_text()) or {})).items()
    }


def coverage() -> dict[str, tuple[int, int]]:
    paths = {scenario_id: name[3] for scenario_id, name in _names().items()}
    found = {tool: [0, 0] for tool in TOOL_NAMES}
    for scenario_id, entry in _entries().items():
        for step in map(_object, _list(entry["chain"])):
            for tool in [step["tool"]] if "tool" in step else _list(step["any_of"]):
                found[str(tool)][paths[scenario_id] == "unhappy"] += 1
    return {tool: (happy, unhappy) for tool, (happy, unhappy) in found.items()}


def _coverage_lines() -> list[str]:
    counts, reasons = coverage(), exceptions()
    complete = [tool for tool, (happy, unhappy) in counts.items() if happy and unhappy]
    lines = [
        "## Tool coverage",
        "",
        f"{len(complete)} of {len(counts)} tools have a happy and an unhappy scenario. "
        + "A test fails for any other tool unless `coverage-exceptions.yaml` gives a reason.",
        "",
        "| Tool | happy | unhappy | Reason |",
        "| --- | --- | --- | --- |",
    ]
    for tool, (happy, unhappy) in sorted(counts.items()):
        if not (happy and unhappy):
            reason = str(reasons.get(tool, {}).get("reason", ""))
            lines.append(f"| `{tool}` | {happy} | {unhappy} | {reason} |")
    return lines


def render_status() -> str:
    names = _names()
    counts: dict[str, dict[str, int]] = {
        surface: {status: 0 for status in _STATUSES} for surface in _SURFACES
    }
    for scenario_id, entry in _entries().items():
        counts[names[scenario_id][0]][str(entry["status"])] += 1
    table = [
        "| Surface | " + " | ".join(_STATUSES) + " | total |",
        "| --- |" + " --- |" * (len(_STATUSES) + 1),
    ]
    for surface in _SURFACES:
        row = counts[surface]
        if sum(row.values()):
            cells = " | ".join(str(row[status]) for status in _STATUSES)
            table.append(f"| {surface} | {cells} | {sum(row.values())} |")
    paths = ["| Surface | happy | unhappy | total |", "| --- | --- | --- | --- |"]
    for surface in _SURFACES:
        found = [path for name_surface, _, _, path in names.values() if name_surface == surface]
        if found:
            happy = found.count("happy")
            paths.append(f"| {surface} | {happy} | {len(found) - happy} | {len(found)} |")
    runs = sum(1 for entry in _entries().values() if {"cassette", "variants"} & set(entry))
    lines = [
        "# office-365-mcp use case status",
        "",
        f"This page is generated by `{_INVOCATION}`. Do not edit it.",
        "",
        "A scenario is `working` when a person ran it by hand, `partly` when a limit blocks a part "
        + "of it, `gap` when nothing meets it today, and `untested` when nobody ran it.",
        "",
        "## Status by surface",
        "",
        *table,
        "",
        f"Scenarios with an executable run: {runs} of {len(_entries())}.",
        "",
        "## Happy and unhappy paths by surface",
        "",
        "A scenario is `@unhappy` when something fails, is refused, is limited, or is hostile.",
        "",
        *paths,
        "",
        "## Work for UN-27222",
        "",
        "These causes are in the connector: a tool, a parameter, a description, or a preset.",
        "",
        *[line for kind in _FIXABLE for line in _blocker_table(kind, names)],
        f"## {_KIND_TITLES['graph']}",
        "",
        *_blocker_table("graph", names)[2:],
        f"## {_KIND_TITLES['unknown']}",
        "",
        *_blocker_table("unknown", names)[2:],
        *_coverage_lines(),
    ]
    return "\n".join(lines).rstrip("\n") + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed page matches what would be generated; exit 1 on drift",
    )
    args = parser.parse_args(argv)

    expected = {TARGET: render(), STATUS: render_status()}
    if not cast("bool", args.check):
        for target, text in expected.items():
            target.write_text(text)
            print(f"wrote {target.relative_to(_ROOT)}")
        return 0

    stale = [target for target, text in expected.items() if target.read_text() != text]
    for target in stale:
        sys.stderr.writelines(
            difflib.unified_diff(
                target.read_text().splitlines(keepends=True),
                expected[target].splitlines(keepends=True),
                fromfile=str(target.relative_to(_ROOT)),
                tofile="generated",
            )
        )
        sys.stderr.write(f"\n{target.name} is stale. Run {_INVOCATION} and commit the result.\n")
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
