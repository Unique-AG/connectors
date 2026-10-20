from pathlib import Path

import pytest

from mcp_architecture import RULES, Rule

ARCHITECTURE = (Path(__file__).parents[1] / "ARCHITECTURE.md").read_text()


@pytest.mark.parametrize("rule", RULES, ids=[rule.name for rule in RULES])
def test_the_architecture_explains_every_rule(rule: Rule) -> None:
    assert f"`{rule.name}`" in ARCHITECTURE
