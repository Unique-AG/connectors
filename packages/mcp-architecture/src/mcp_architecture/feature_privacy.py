import ast
import importlib.util
from pathlib import Path
from typing import cast, override

from grimp import ImportGraph
from importlinter import Contract, ContractCheck, fields, output
from importlinter.domain.imports import Module


class FeaturePrivacyContract(Contract):
    """Only a feature reaches inside itself. Everyone else imports the feature's top level.

    The built-in `protected` contract cannot say this: an allowed importer's descendants are
    allowed too, so `orders.place_order` could import `products.lookup.get_product` unnoticed.

    `from <feature> import name` names the submodule `name` when there is one, and the import
    graph records the submodule. It is an import of the top level only when the top level
    re-exports the function of the same name from it, with `from <feature>.name import name`.
    Otherwise it hands the importer the module, and every name in it.
    """

    container: fields.ModuleField = fields.ModuleField()

    @override
    def check(self, graph: ImportGraph, verbose: bool) -> ContractCheck:
        # importlinter replaces each field on the instance with its parsed value.
        container: Module = self.container  # pyright: ignore[reportAssignmentType]
        violations = [
            f"{importer} imports {internal}, which is internal to its feature (l.{line})"
            for feature in sorted(graph.find_children(container.name))
            for re_exported in [_same_name_re_exports(feature)]
            for internal in sorted(graph.find_descendants(feature))
            for importer in sorted(graph.find_modules_that_directly_import(internal))
            if importer != feature and not importer.startswith(f"{feature}.")
            for line in sorted(
                detail["line_number"]
                for detail in graph.get_import_details(importer=importer, imported=internal)
                if not (
                    detail["line_contents"].startswith(f"from {feature} import ")
                    and internal in re_exported
                )
            )
        ]
        return ContractCheck(kept=not violations, metadata={"violations": violations})

    @override
    def render_broken_contract(self, check: ContractCheck) -> None:
        assert check.metadata is not None, "check() always sets metadata"
        for violation in cast(list[str], check.metadata["violations"]):
            output.print_error(f"- {violation}")
        output.new_line()


def _same_name_re_exports(feature: str) -> set[str]:
    """Each submodule `<feature>.name` whose `__init__.py` imports `name` from it as `name`."""
    root, *parts = feature.split(".")
    # A top-level package's spec is found without importing it, so none of its code runs.
    spec = importlib.util.find_spec(root)
    assert spec is not None and spec.submodule_search_locations, f"{root} is not a package"
    init = Path(next(iter(spec.submodule_search_locations)), *parts, "__init__.py")
    if not init.is_file():
        return set()
    return {
        node.module
        for node in ast.parse(init.read_text()).body
        if isinstance(node, ast.ImportFrom) and node.module is not None
        for name in [node.module.removeprefix(f"{feature}.")]
        if node.module == f"{feature}.{name}"
        and any(alias.name == name and alias.asname in {None, name} for alias in node.names)
    }
