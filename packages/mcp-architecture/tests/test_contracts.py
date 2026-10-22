import importlib
import sys
from pathlib import Path

import pytest
from importlinter.application.output import console

from mcp_architecture.imports import check_imports

SHOP = {
    "__init__.py": "",
    "main.py": "from shop.mcp import serve\n",
    "mcp/__init__.py": "from shop.contexts import place_order\n\nserve = place_order\n",
    "mcp/tools/__init__.py": "",
    "contexts/__init__.py": (
        "from shop.contexts.orders import place_order\n"
        "from shop.contexts.products import get_product\n\n"
        '__all__ = ["get_product", "place_order"]\n'
    ),
    "contexts/orders/__init__.py": "from shop.contexts.orders.place_order import place_order\n",
    "contexts/orders/place_order.py": (
        "from shop.contexts.products import get_product\n"
        "from shop.upstream import Upstream\n\n\n"
        "def place_order(*, upstream: Upstream, product_id: str) -> str:\n"
        "    return get_product(upstream=upstream, product_id=product_id)\n"
    ),
    "contexts/products/__init__.py": (
        "from shop.contexts.products.lookup.get_product import get_product\n"
    ),
    "contexts/products/lookup/__init__.py": "",
    "contexts/products/lookup/get_product.py": (
        "from shop.upstream import Upstream\n\n\n"
        "def get_product(*, upstream: Upstream, product_id: str) -> str:\n"
        "    return upstream.name + product_id\n"
    ),
    "upstream/__init__.py": "from shop.upstream.client import Upstream, UpstreamError\n",
    "upstream/client.py": (
        "from fastmcp.exceptions import ToolError\n\n\n"
        "class UpstreamError(ToolError): ...\n\n\n"
        "class Upstream:\n    name = 'upstream'\n"
    ),
    "persistence/__init__.py": "",
    "utils/__init__.py": "",
    "telemetry/__init__.py": "",
}

PROJECT = '[project]\nname = "shop"\n\n'


@pytest.fixture
def shop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A service that keeps the contracts, its package `shop` under `src`, with no contract of
    its own."""
    for relative, text in SHOP.items():
        write(tmp_path, relative, text)
    (tmp_path / "pyproject.toml").write_text(
        f'{PROJECT}[tool.importlinter]\nroot_package = "shop"\n'
    )
    monkeypatch.setattr(sys, "path", [str(tmp_path / "src"), *sys.path])
    importlib.invalidate_caches()
    return tmp_path


def write(root: Path, relative: str, text: str) -> None:
    path = root / "src" / "shop" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def broken_contracts(root: Path) -> str:
    """import-linter's report, with its lines unwrapped, or nothing when every contract holds."""
    with console.capture() as captured:
        exit_code = check_imports(root)
    return "" if exit_code == 0 else " ".join(captured.get().split())


def test_a_service_that_keeps_the_architecture_breaks_no_contract(shop: Path) -> None:
    assert broken_contracts(shop) == ""


def test_the_mcp_layer_importing_a_feature_breaks_the_contexts_contract(shop: Path) -> None:
    write(shop, "mcp/tools/order.py", "from shop.contexts.orders import place_order\n")

    report = broken_contracts(shop)

    assert "contexts is imported through its top level only" in report
    assert "shop.mcp.tools.order -> shop.contexts.orders" in report


def test_a_feature_reaching_inside_another_breaks_the_feature_privacy(shop: Path) -> None:
    write(
        shop,
        "contexts/orders/place_order.py",
        "from shop.contexts.products.lookup.get_product import get_product\n",
    )

    report = broken_contracts(shop)

    assert (
        "shop.contexts.orders.place_order imports shop.contexts.products.lookup.get_product, "
        "which is internal to its feature"
    ) in report


def test_a_feature_reaching_a_submodule_through_another_features_top_level_breaks_it(
    shop: Path,
) -> None:
    write(shop, "contexts/orders/place_order.py", "from shop.contexts.products import lookup\n")

    report = broken_contracts(shop)

    assert "shop.contexts.orders.place_order imports shop.contexts.products.lookup" in report


def test_a_feature_reaching_a_module_another_feature_re_exports_a_name_from_breaks_it(
    shop: Path,
) -> None:
    write(shop, "contexts/products/models.py", "class Product: ...\n\n\nclass Secret: ...\n")
    write(
        shop,
        "contexts/products/__init__.py",
        "from shop.contexts.products.lookup.get_product import get_product\n"
        "from shop.contexts.products.models import Product\n",
    )
    write(shop, "contexts/orders/place_order.py", "from shop.contexts.products import models\n")

    report = broken_contracts(shop)

    assert "shop.contexts.orders.place_order imports shop.contexts.products.models" in report


def test_a_feature_importing_a_function_another_feature_re_exports_keeps_it(shop: Path) -> None:
    write(shop, "contexts/products/get_price.py", "def get_price() -> int:\n    return 1\n")
    write(
        shop,
        "contexts/products/__init__.py",
        "from shop.contexts.products.get_price import get_price\n"
        "from shop.contexts.products.lookup.get_product import get_product\n",
    )
    write(
        shop,
        "contexts/orders/place_order.py",
        "from shop.contexts.products import get_price\n\n\ndef place_order() -> int:\n"
        "    return get_price()\n",
    )

    assert broken_contracts(shop) == ""


def test_features_importing_each_other_break_the_acyclic_contract(shop: Path) -> None:
    write(
        shop, "contexts/products/lookup/stock.py", "from shop.contexts.orders import place_order\n"
    )

    report = broken_contracts(shop)

    assert "No package imports its siblings in a cycle" in report
    assert "No cycles are allowed in shop.contexts" in report


def test_packages_inside_a_layer_importing_each_other_break_the_acyclic_contract(
    shop: Path,
) -> None:
    write(shop, "mcp/tools/order.py", "import shop.mcp.inputs\n")
    write(shop, "mcp/inputs/__init__.py", "import shop.mcp.tools.order\n")

    report = broken_contracts(shop)

    assert "No package imports its siblings in a cycle" in report
    assert "No cycles are allowed in shop.mcp" in report


@pytest.mark.parametrize(
    "layer", ["contexts/orders/errors.py", "persistence/errors.py", "utils/errors.py"]
)
@pytest.mark.parametrize(
    ("statement", "package"),
    [
        ("from fastmcp.exceptions import ToolError", "fastmcp"),
        ("from mcp_types import ToolAnnotations", "mcp_types"),
    ],
)
def test_the_domain_the_storage_or_utils_importing_mcp_breaks_the_contract(
    shop: Path, layer: str, statement: str, package: str
) -> None:
    write(shop, layer, f"{statement}\n")

    report = broken_contracts(shop)

    assert "The domain, the storage and utils know nothing about MCP" in report
    assert f"-> {package}" in report


def test_the_domain_reaching_mcp_through_utils_breaks_the_contract(shop: Path) -> None:
    write(shop, "utils/__init__.py", "from fastmcp.exceptions import ToolError\n")
    write(shop, "contexts/orders/errors.py", "from shop.utils import ToolError\n")

    report = broken_contracts(shop)

    assert "The domain, the storage and utils know nothing about MCP" in report
    assert "shop.utils -> fastmcp" in report


@pytest.mark.parametrize("layer", ["mcp", "contexts", "upstream", "persistence"])
def test_every_layer_above_utils_may_use_it(shop: Path, layer: str) -> None:
    write(shop, "utils/__init__.py", "import shop.telemetry\n")
    write(shop, f"{layer}/helpers.py", "import shop.utils\n")

    assert broken_contracts(shop) == ""


@pytest.mark.parametrize("layer", ["mcp", "contexts", "upstream", "persistence"])
def test_utils_importing_a_layer_above_it_breaks_the_layers_contract(
    shop: Path, layer: str
) -> None:
    write(shop, "utils/__init__.py", f"import shop.{layer}\n")

    report = broken_contracts(shop)

    assert "Layers only import downwards" in report
    assert f"shop.utils -> shop.{layer}" in report


def test_a_module_outside_the_layers_breaks_the_layers_contract(shop: Path) -> None:
    write(shop, "logic.py", "")

    report = broken_contracts(shop)

    assert "Layers only import downwards" in report
    assert "shop.logic" in report


OWN_CONTRACT = (
    "\n[[tool.importlinter.contracts]]\n"
    'name = "Orders know nothing about payments"\n'
    'type = "forbidden"\n'
    'source_modules = ["shop.contexts.orders"]\n'
    'forbidden_modules = ["shop.contexts.payments"]\n'
)
ALWAYS_KEPT = (
    "from importlinter.domain.contract import Contract, ContractCheck\n\n\n"
    "class AlwaysKept(Contract):\n"
    "    def check(self, graph, verbose):\n"
    "        return ContractCheck(kept=True, warnings=[])\n\n"
    "    def render_broken_contract(self, check): ...\n"
)


def test_a_broken_contract_of_the_mcps_own_breaks_the_check(shop: Path) -> None:
    pyproject = shop / "pyproject.toml"
    pyproject.write_text(pyproject.read_text() + OWN_CONTRACT)
    write(shop, "contexts/payments/__init__.py", "")
    write(shop, "contexts/orders/refund.py", "import shop.contexts.payments\n")

    assert "Orders know nothing about payments" in broken_contracts(shop)


@pytest.mark.parametrize("kind", ["layers", "feature_privacy"])
def test_an_own_contract_type_of_a_shared_name_does_not_turn_the_shared_contract_off(
    shop: Path, kind: str
) -> None:
    (shop / "src" / "shop_checks.py").write_text(ALWAYS_KEPT)
    pyproject = shop / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text() + f'contract_types = ["{kind}: shop_checks.AlwaysKept"]\n'
    )
    write(shop, "utils/__init__.py", "import shop.mcp\n")

    assert "Layers only import downwards" in broken_contracts(shop)


def test_an_mcp_without_an_importlinter_table_still_keeps_the_shared_contracts(
    shop: Path,
) -> None:
    (shop / "pyproject.toml").write_text(PROJECT)
    write(shop, "utils/__init__.py", "import shop.mcp\n")

    assert "Layers only import downwards" in broken_contracts(shop)
