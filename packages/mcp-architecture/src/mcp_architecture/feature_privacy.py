from typing import cast, override

from grimp import ImportGraph
from importlinter import Contract, ContractCheck, fields, output
from importlinter.domain.imports import Module


class FeaturePrivacyContract(Contract):
    """Only a feature reaches inside itself. Everyone else imports the feature's top level.

    The built-in `protected` contract cannot say this: an allowed importer's descendants are
    allowed too, so `orders.place_order` could import `products.lookup.get_product` unnoticed.

    `from <feature> import name` is an import of the top level when the top level imports the
    submodule `name` itself, to re-export the function of the same name from it: the import graph
    records the submodule all the same.
    """

    container: fields.ModuleField = fields.ModuleField()

    @override
    def check(self, graph: ImportGraph, verbose: bool) -> ContractCheck:
        # importlinter replaces each field on the instance with its parsed value.
        container: Module = self.container  # pyright: ignore[reportAssignmentType]
        violations = [
            f"{importer} imports {internal}, which is internal to its feature (l.{line})"
            for feature in sorted(graph.find_children(container.name))
            for internal in sorted(graph.find_descendants(feature))
            for importer in sorted(graph.find_modules_that_directly_import(internal))
            if importer != feature and not importer.startswith(f"{feature}.")
            for line in sorted(
                detail["line_number"]
                for detail in graph.get_import_details(importer=importer, imported=internal)
                if not _is_re_export(graph, detail["line_contents"], feature, internal)
            )
        ]
        return ContractCheck(kept=not violations, metadata={"violations": violations})

    @override
    def render_broken_contract(self, check: ContractCheck) -> None:
        assert check.metadata is not None, "check() always sets metadata"
        for violation in cast(list[str], check.metadata["violations"]):
            output.print_error(f"- {violation}")
        output.new_line()


def _is_re_export(graph: ImportGraph, line: str, feature: str, internal: str) -> bool:
    return line.startswith(f"from {feature} import ") and graph.direct_import_exists(
        importer=feature, imported=internal
    )
