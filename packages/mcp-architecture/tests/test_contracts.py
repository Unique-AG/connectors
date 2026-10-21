import importlib
import sys
from pathlib import Path

import pytest
from importlinter.application.output import console
from importlinter.cli import lint_imports

from mcp_architecture import render_importlinter

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
    "telemetry/__init__.py": "",
}


@pytest.fixture
def shop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A service that keeps the contracts, its package `shop` under `src`."""
    for relative, text in SHOP.items():
        write(tmp_path, relative, text)
    (tmp_path / "pyproject.toml").write_text(render_importlinter("shop"))
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
        exit_code = lint_imports(
            config_filename=str(root / "pyproject.toml"), no_cache=True, no_logo=True
        )
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


@pytest.mark.parametrize("layer", ["contexts/orders/errors.py", "persistence/errors.py"])
def test_the_domain_or_the_storage_importing_fastmcp_breaks_the_contract(
    shop: Path, layer: str
) -> None:
    write(shop, layer, "from fastmcp.exceptions import ToolError\n")

    report = broken_contracts(shop)

    assert "The domain and the storage know nothing about MCP" in report
    assert "-> fastmcp" in report


def test_a_module_outside_the_layers_breaks_the_layers_contract(shop: Path) -> None:
    write(shop, "logic.py", "")

    report = broken_contracts(shop)

    assert "Layers only import downwards" in report
    assert "shop.logic" in report
