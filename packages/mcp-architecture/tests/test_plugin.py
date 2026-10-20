import pytest

from mcp_architecture import RULES, render_importlinter
from tests.shop import TYPE_CHECK_TABLE, write_shop

# asyncio_mode stays pytest-asyncio's default, strict, which the async checks must work under.
PYTEST_TABLE = """[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
"""
CONFTEST = '''from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field
import pytest


@pytest.fixture
def server() -> FastMCP:
    mcp = FastMCP(name="Shop")

    @mcp.tool
    def get_product(product_id: Annotated[str, Field(description="The product.")]) -> str:
        """Read one product."""
        return product_id

    return mcp
'''
CHECKS = len(RULES) + 2


@pytest.fixture
def shop(pytester: pytest.Pytester) -> pytest.Pytester:
    write_shop(pytester.path)
    pytester.makepyprojecttoml(f"{PYTEST_TABLE}\n{TYPE_CHECK_TABLE}\n{render_importlinter('shop')}")
    (pytester.path / "tests").mkdir()
    (pytester.path / "tests" / "__init__.py").write_text("")
    (pytester.path / "tests" / "conftest.py").write_text(CONFTEST)
    return pytester


def test_the_checks_join_the_tests_of_a_service_that_declares_contracts(
    shop: pytest.Pytester,
) -> None:
    result = shop.runpytest_subprocess("--regen-all", "-v")

    result.assert_outcomes(passed=CHECKS)
    result.stdout.fnmatch_lines(
        ["tests/mcp_architecture.py::test_the_service_keeps_the_architecture?import-contracts? *"]
    )
    assert (shop.path / "tests" / "tool_surface.generated.json").is_file()


def test_a_missing_snapshot_fails_the_service(shop: pytest.Pytester) -> None:
    result = shop.runpytest_subprocess()

    result.assert_outcomes(passed=CHECKS - 1, failed=1)
    result.stdout.fnmatch_lines(["*test_the_tools_served_match_their_snapshot*"])


def test_a_broken_rule_fails_the_service(shop: pytest.Pytester) -> None:
    (shop.path / "src" / "shop" / "contexts" / "billing" / "queries").mkdir(parents=True)
    (shop.path / "src" / "shop" / "contexts" / "billing" / "queries" / "__init__.py").write_text("")

    result = shop.runpytest_subprocess("--regen-all")

    result.assert_outcomes(passed=CHECKS - 1, failed=1)
    result.stdout.fnmatch_lines(["*billing needs an __init__.py*"])


def test_a_project_without_contracts_gets_no_checks(pytester: pytest.Pytester) -> None:
    pytester.makepyprojecttoml(PYTEST_TABLE)
    pytester.mkpydir("tests")
    (pytester.path / "tests" / "test_one.py").write_text("def test_one() -> None:\n    pass\n")

    pytester.runpytest_subprocess().assert_outcomes(passed=1)


def test_a_project_that_depends_on_the_architecture_without_contracts_fails(
    pytester: pytest.Pytester,
) -> None:
    pytester.makepyprojecttoml(
        f'[dependency-groups]\ndev = ["mcp-architecture==0.1.0"]\n\n{PYTEST_TABLE}'
    )
    write_shop(pytester.path)
    pytester.mkpydir("tests")
    (pytester.path / "tests" / "test_one.py").write_text("def test_one() -> None:\n    pass\n")

    result = pytester.runpytest_subprocess()

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*depends on mcp-architecture but has no [[]tool.importlinter]*"])


def test_a_package_that_uses_the_architecture_without_contexts_gets_no_checks(
    pytester: pytest.Pytester,
) -> None:
    pytester.makepyprojecttoml(
        f'[project]\nname = "scaffold"\ndependencies = ["mcp-architecture"]\n\n{PYTEST_TABLE}'
    )
    pytester.mkpydir("tests")
    (pytester.path / "tests" / "test_one.py").write_text("def test_one() -> None:\n    pass\n")

    pytester.runpytest_subprocess().assert_outcomes(passed=1)
