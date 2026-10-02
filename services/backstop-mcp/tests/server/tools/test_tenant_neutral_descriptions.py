"""Published core text describes Backstop, not one firm's taxonomy."""

import re
from collections.abc import Iterator
from typing import cast

from fastmcp import FastMCP

from backstop_mcp.server.instructions import INSTRUCTIONS
from backstop_mcp.server.tools import TOOLS

# Case-sensitive where a lower-case spelling is generic core text.
# `\bDomicile\b` does not match pydantic's "Us Domiciled" title.
# "Investor Type" stays capitalized: lower-case "investor type" is generic.
# "IDD" stays capitalized: lower case matches "hidden" and "middle_name".
_DENYLIST: tuple[re.Pattern[str], ...] = (
    re.compile(r"Convert Arb"),
    re.compile(r"Convertible"),
    re.compile(r"converts"),
    re.compile(r"Converts"),
    re.compile(r"dispersion"),
    re.compile(r"long vol"),
    re.compile(r"Investor Status"),
    re.compile(r"Investor Type"),
    re.compile(r"\bGrade\b"),
    re.compile(r"Fee Structure"),
    re.compile(r"\bDomicile\b"),
    re.compile(r"Opportunity Type"),
    re.compile(r"\bProspect\b"),
    re.compile(r"\bprospect\b"),
    re.compile(r"\bIDD\b"),
    re.compile(r"onshore"),
    re.compile(r"offshore"),
    re.compile(r"feeder"),
    re.compile(r"XY:"),
    re.compile(r"Master Pipeline"),
    re.compile(r"colleague updates"),
    re.compile(r"pull my"),
    re.compile(r"transaction type"),
)


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        for child in cast("dict[object, object]", value).values():
            yield from _strings(child)
        return
    if isinstance(value, list):
        for child in cast("list[object]", value):
            yield from _strings(child)


def test_published_text_does_not_name_a_tenant_taxonomy() -> None:
    mcp = FastMCP("tenant-neutral")
    texts = [INSTRUCTIONS]
    for fn in TOOLS:
        tool = mcp.add_tool(fn)
        if tool.description:
            texts.append(tool.description)
        texts.extend(_strings(tool.parameters))
        texts.extend(_strings(tool.output_schema))

    hits = [
        f"{pattern.pattern!r} in {snippet!r}"
        for text in texts
        for pattern in _DENYLIST
        if pattern.search(text)
        for snippet in (text if len(text) <= 160 else text[:160],)
    ]
    assert not hits, "tenant wording in published core text:\n  " + "\n  ".join(hits)
