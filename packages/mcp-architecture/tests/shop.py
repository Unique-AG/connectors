from pathlib import Path

import mcp_architecture

TYPE_CHECK = Path(mcp_architecture.__file__).parent / "type_check.json"
TYPE_CHECK_TABLE = f'[tool.basedpyright]\nextends = "{TYPE_CHECK}"\n'

PACKAGE_FILES = {
    "__init__.py": "",
    "main.py": (
        'from shop.mcp import serve\n\n\ndef main() -> str:\n    return serve(product_id="p-1")\n'
    ),
    "mcp/__init__.py": "from shop.contexts.orders import place_order\n\nserve = place_order\n",
    "mcp/tools/__init__.py": "",
    "contexts/__init__.py": "",
    "contexts/orders/__init__.py": (
        "from shop.contexts.orders.commands.place_order import place_order\n\n"
        '__all__ = ["place_order"]\n'
    ),
    "contexts/orders/commands/__init__.py": "",
    "contexts/orders/commands/place_order.py": (
        "from shop.contexts.products import get_product\n\n\n"
        "def place_order(*, product_id: str) -> str:\n"
        "    return get_product(product_id=product_id)\n"
    ),
    "contexts/products/__init__.py": (
        "from shop.contexts.products.queries.get_product import get_product\n\n"
        '__all__ = ["get_product"]\n'
    ),
    "contexts/products/queries/__init__.py": "",
    "contexts/products/queries/get_product.py": (
        "def get_product(*, product_id: str) -> str:\n    return _ask(product_id=product_id)\n\n\n"
        "def _ask(*, product_id: str) -> str:\n    return product_id\n"
    ),
    "upstream/__init__.py": "",
    "persistence/__init__.py": "",
    "telemetry/__init__.py": "",
}


def write_shop(root: Path) -> None:
    """A service that keeps the architecture, its package `shop` under `root/src`."""
    for relative, text in PACKAGE_FILES.items():
        path = root / "src" / "shop" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
