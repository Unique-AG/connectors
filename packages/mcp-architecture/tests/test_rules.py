import importlib
import json
import sys
from pathlib import Path

import pytest

from mcp_architecture import RULES, Rule, Service, render_importlinter, required_contracts
from mcp_architecture.contracts import LAYERS
from tests.shop import TYPE_CHECK, TYPE_CHECK_TABLE, write_shop


@pytest.fixture
def service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Service:
    write_shop(tmp_path)
    (tmp_path / "pyproject.toml").write_text(f"{TYPE_CHECK_TABLE}\n{render_importlinter('shop')}")
    monkeypatch.setattr(sys, "path", [str(tmp_path / "src"), *sys.path])
    importlib.invalidate_caches()
    return Service(tmp_path)


def rule(name: str) -> Rule:
    return next(rule for rule in RULES if rule.name == name)


def write(service: Service, relative: str, text: str) -> None:
    path = service.source / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def write_invoice_query(service: Service, *, list_orders: str, get_invoice: str) -> None:
    """orders exports a command and a query side by side; invoices has a query that uses orders."""
    write(
        service,
        "contexts/orders/__init__.py",
        "from shop.contexts.orders.commands.place_order import place_order\n"
        "from shop.contexts.orders.queries.list_orders import list_orders\n\n"
        '__all__ = ["list_orders", "place_order"]\n',
    )
    write(service, "contexts/orders/queries/__init__.py", "")
    write(service, "contexts/orders/queries/list_orders.py", list_orders)
    write(service, "contexts/invoices/__init__.py", "")
    write(service, "contexts/invoices/queries/__init__.py", "")
    write(service, "contexts/invoices/queries/get_invoice.py", get_invoice)


def unwrapped(problem: str) -> str:
    """import-linter wraps its report to the terminal's width."""
    return " ".join(problem.split())


def set_session_option(service: Service, option: str) -> None:
    table = service.pyproject.read_text()
    service.pyproject.write_text(
        table.replace("[tool.importlinter]\n", f"[tool.importlinter]\n{option}\n")
    )


LIST_ORDERS = "def list_orders(*, product_id: str) -> list[str]:\n    return [product_id]\n"


@pytest.mark.parametrize("kept", RULES, ids=[rule.name for rule in RULES])
def test_a_service_that_keeps_the_architecture_breaks_no_rule(service: Service, kept: Rule) -> None:
    assert kept.check(service) == []


def test_a_feature_reaching_inside_another_breaks_the_import_contracts(service: Service) -> None:
    write(
        service,
        "contexts/orders/commands/place_order.py",
        "from shop.contexts.products.queries.get_product import get_product\n\n\n"
        "def place_order(*, product_id: str) -> str:\n"
        "    return get_product(product_id=product_id)\n",
    )

    [problem] = rule("import-contracts").check(service)

    assert "shop.contexts.orders.commands.place_order imports" in problem
    assert "internal to its feature" in problem


def test_a_query_reaching_a_command_breaks_the_import_contracts(service: Service) -> None:
    write(
        service,
        "contexts/products/queries/get_product.py",
        "from shop.contexts.orders import place_order\n\n\n"
        "def get_product(*, product_id: str) -> str:\n"
        "    return place_order(product_id=product_id)\n",
    )

    [problem] = rule("import-contracts").check(service)

    assert "shop.contexts.products.queries.get_product -> " in problem


@pytest.mark.parametrize(
    "get_invoice",
    [
        "from shop.contexts.orders import list_orders\n\n\n"
        "def get_invoice(*, product_id: str) -> list[str]:\n"
        "    return list_orders(product_id=product_id)\n",
        "from shop.contexts import orders\n\n\n"
        "def get_invoice(*, product_id: str) -> list[str]:\n"
        "    return orders.list_orders(product_id=product_id)\n",
    ],
    ids=["from-the-feature", "through-the-feature-module"],
)
def test_a_query_using_a_query_beside_a_command_in_a_top_level_keeps_the_import_contracts(
    service: Service, get_invoice: str
) -> None:
    write_invoice_query(service, list_orders=LIST_ORDERS, get_invoice=get_invoice)

    assert rule("import-contracts").check(service) == []


def test_a_query_taking_a_command_through_the_feature_module_breaks_the_import_contracts(
    service: Service,
) -> None:
    write_invoice_query(
        service,
        list_orders=LIST_ORDERS,
        get_invoice="from shop.contexts import orders\n\n\n"
        "def get_invoice(*, product_id: str) -> str:\n"
        "    return orders.place_order(product_id=product_id)\n",
    )

    [problem] = rule("import-contracts").check(service)

    assert (
        "- shop.contexts.invoices.queries.get_invoice -> shop.contexts.orders.commands.place_order"
        in unwrapped(problem)
    )


def test_a_query_reaching_a_command_through_another_query_breaks_the_import_contracts(
    service: Service,
) -> None:
    write_invoice_query(
        service,
        list_orders="from shop.contexts.orders.commands.place_order import place_order\n\n\n"
        "def list_orders(*, product_id: str) -> list[str]:\n"
        "    return [place_order(product_id=product_id)]\n",
        get_invoice="from shop.contexts.orders import list_orders\n\n\n"
        "def get_invoice(*, product_id: str) -> list[str]:\n"
        "    return list_orders(product_id=product_id)\n",
    )

    [problem] = rule("import-contracts").check(service)

    assert (
        "- shop.contexts.invoices.queries.get_invoice -> shop.contexts.orders.queries.list_orders "
        "-> shop.contexts.orders.commands.place_order" in unwrapped(problem)
    )


def test_a_session_option_that_loosens_every_contract_breaks_the_required_contracts(
    service: Service,
) -> None:
    set_session_option(service, "exclude_type_checking_imports = true")

    assert rule("required-contracts").check(service) == [
        "[tool.importlinter] may not set exclude_type_checking_imports"
    ]


def test_including_external_packages_keeps_the_contracts(service: Service) -> None:
    set_session_option(service, "include_external_packages = true")

    assert rule("required-contracts").check(service) == []
    assert rule("import-contracts").check(service) == []


def test_a_loosened_contract_breaks_the_required_contracts(service: Service) -> None:
    table = render_importlinter("shop")
    without_the_last = table[: table.rindex("\n[[tool.importlinter.contracts]]\n") + 1]
    ignore = ["shop.upstream -> shop.mcp"]
    layers_line = f"layers = {json.dumps(LAYERS)}\n"
    loosened = without_the_last.replace(
        layers_line, f"{layers_line}ignore_imports = {json.dumps(ignore)}\n"
    )
    service.pyproject.write_text(loosened)

    problems = rule("required-contracts").check(service)

    layers = required_contracts("shop")[0]
    loosened_layers = {**layers, "ignore_imports": ignore}
    assert problems == [
        f"'Layers only import downwards' was changed to {loosened_layers}; it must be {layers}",
        "'telemetry is imported through its top level only' is missing",
    ]


def test_a_contract_type_redefining_a_required_one_breaks_the_required_contracts(
    service: Service,
) -> None:
    table = service.pyproject.read_text()
    service.pyproject.write_text(
        table.replace("contract_types = [\n", 'contract_types = [\n    "layers: shop.Kept",\n')
    )

    assert rule("required-contracts").check(service) == [
        "contract_types may not redefine a type the required contracts use: 'layers: shop.Kept'"
    ]


def test_ruff_rules_the_architecture_relies_on_break_the_required_lint_whatever_ruff_is_told(
    service: Service,
) -> None:
    service.pyproject.write_text(
        '[tool.ruff.lint]\nselect = ["E"]\nextend-ignore = ["INP001", "N999", "TID252"]\n\n'
        f"{render_importlinter('shop')}"
    )
    write(service, "contexts/products/queries/GetPrice.py", "")
    write(service, "mcp/tools/formatting/money.py", "from . import cents  # noqa: TID252\n")

    problems = rule("required-lint").check(service)

    assert [" ".join(problem.split()[:2]) for problem in problems] == [
        "src/shop/contexts/products/queries/GetPrice.py:1:1: N999",
        "src/shop/mcp/tools/formatting/money.py:1:1: INP001",
        "src/shop/mcp/tools/formatting/money.py:1:1: TID252",
    ]


def test_code_against_the_style_breaks_it_whatever_the_service_configures(
    service: Service,
) -> None:
    service.pyproject.write_text(
        f'[tool.ruff.lint]\nignore = ["ALL"]\n\n{render_importlinter("shop")}'
    )
    write(
        service,
        "telemetry/counters.py",
        "def count(Total: int) -> int:\n"
        "    try:\n"
        "        return Total + 1\n"
        "    except:\n"
        "        return 0\n",
    )

    problems = rule("code-style").check(service)

    assert [problem.split()[1] for problem in problems] == ["N803", "E722"]


def test_the_mcps_departures_from_googles_style_keep_it(service: Service) -> None:
    write(service, "telemetry/notes.py", f'NOTE = "{"x" * 85}"\n')
    (service.root / "tests").mkdir()
    (service.root / "tests" / "__init__.py").write_text("")
    (service.root / "tests" / "test_notes.py").write_text(
        "from shop.telemetry.notes import NOTE\n\n\ndef test_note() -> None:\n    assert NOTE\n"
    )

    assert rule("code-style").check(service) == []


def test_the_style_skips_the_code_generated_from_a_vendors_spec(service: Service) -> None:
    service.pyproject.write_text(
        '[tool.mcp-openapi]\nmodels-output = "src/shop/upstream/vendor_responses.py"\n\n'
        f"{render_importlinter('shop')}"
    )
    write(service, "upstream/vendor_responses.py", "class Order:\n    productId: str\n")

    assert rule("code-style").check(Service(service.root)) == []


def set_type_check(service: Service, table: str) -> Service:
    service.pyproject.write_text(f"{table}\n{render_importlinter('shop')}")
    return Service(service.root)


def test_a_type_check_that_does_not_extend_the_shared_one_breaks_the_rule(
    service: Service,
) -> None:
    loose = set_type_check(service, '[tool.basedpyright]\ntypeCheckingMode = "all"\n')

    assert rule("type-check").check(loose) == [
        "[tool.basedpyright] must extend mcp-architecture's type_check.json"
    ]


def test_a_type_check_that_turns_a_report_down_breaks_the_rule(service: Service) -> None:
    loose = set_type_check(
        service,
        f"{TYPE_CHECK_TABLE}"
        'typeCheckingMode = "basic"\n'
        "reportAny = false\n"
        'reportUnknownMemberType = "warning"\n'
        'ignore = ["src/shop/upstream"]\n',
    )

    assert rule("type-check").check(loose) == [
        "[tool.basedpyright] may not set typeCheckingMode = 'basic'",
        "[tool.basedpyright] may not set reportAny = False",
        "[tool.basedpyright] may not set reportUnknownMemberType = 'warning'",
        "[tool.basedpyright] may not set ignore = ['src/shop/upstream']",
    ]


def test_a_type_check_made_stricter_or_restated_keeps_the_rule(service: Service) -> None:
    strict = set_type_check(
        service,
        f"{TYPE_CHECK_TABLE}"
        'pythonVersion = "3.14"\n'
        'include = ["src", "tests"]\n'
        'typeCheckingMode = "all"\n'
        "reportUnusedCallResult = true\n"
        'reportImplicitStringConcatenation = "error"\n'
        "reportMissingTypeStubs = false\n",
    )

    assert rule("type-check").check(strict) == []


def test_a_pyrightconfig_beside_the_table_breaks_the_type_check(service: Service) -> None:
    (service.root / "pyrightconfig.json").write_text(TYPE_CHECK.read_text())

    assert rule("type-check").check(service) == [
        "pyrightconfig.json replaces [tool.basedpyright]; remove it"
    ]


def test_a_context_folder_without_an_init_breaks_the_feature_packages(service: Service) -> None:
    write(service, "contexts/billing/queries/__init__.py", "")

    assert rule("feature-packages").check(service) == ["billing needs an __init__.py"]


def test_a_feature_folder_outside_commands_and_queries_or_nested_breaks_the_rule(
    service: Service,
) -> None:
    write(service, "contexts/orders/helpers/__init__.py", "")
    write(service, "contexts/orders/commands/place_order/steps/__init__.py", "")

    assert rule("feature-folders").check(service) == [
        "orders may only have ['commands', 'queries'] folders, not helpers",
        "orders/commands/place_order nests steps",
    ]


def test_a_nested_tool_folder_breaks_the_rule(service: Service) -> None:
    write(service, "mcp/tools/place_order/inputs/__init__.py", "")

    assert rule("tool-folders").check(service) == ["tools/place_order nests inputs"]


def test_a_feature_init_that_defines_a_name_breaks_the_rule(service: Service) -> None:
    write(
        service,
        "contexts/products/__init__.py",
        '"""Products."""\n\n'
        "from shop.contexts.products.queries.get_product import get_product\n\n"
        "LIMIT = 10\n\n"
        '__all__ = ["get_product"]\n',
    )

    assert rule("feature-inits").check(service) == [
        "products/__init__.py:5: define it in a command, a query or a model module, and "
        "re-export it here"
    ]


def test_a_context_module_with_two_public_functions_or_a_constant_breaks_the_rule(
    service: Service,
) -> None:
    write(
        service,
        "contexts/products/queries/list_products.py",
        "class Page:\n    pass\n\n\nLIMIT = 10\n\n\n"
        "def list_products(*, page: Page) -> list[str]:\n    return []\n\n\n"
        "def count_products(*, page: Page) -> int:\n    return 0\n",
    )

    assert rule("one-public-function").check(service) == [
        "products/queries/list_products.py: keep one public function, make the others "
        "private: ['list_products', 'count_products']",
        "products/queries/list_products.py: define list_products first",
        "products/queries/list_products.py: make module constants private: ['LIMIT']",
    ]


def test_a_public_context_function_with_positional_parameters_breaks_the_rule(
    service: Service,
) -> None:
    write(
        service,
        "contexts/products/queries/get_product.py",
        "def get_product(product_id: str) -> str:\n    return product_id\n",
    )

    assert rule("keyword-only").check(service) == [
        "products/queries/get_product.py: put a bare * before the parameters of get_product"
    ]
