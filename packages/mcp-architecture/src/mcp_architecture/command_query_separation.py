import ast
from collections import deque
from importlib.util import find_spec
from pathlib import Path
from typing import cast, override

from grimp import ImportGraph
from importlinter import Contract, ContractCheck, fields, output
from importlinter.domain.imports import Module


class CommandQuerySeparationContract(Contract):
    """A query never reaches a command, directly or through other modules. Commands may use
    queries.

    A feature's `__init__.py` re-exports its commands and queries together, so following the
    import graph alone would flag every query that uses another feature's query. An import from
    a feature's top level is followed to the modules that define the names it takes instead.
    """

    container: fields.ModuleField = fields.ModuleField()

    @override
    def check(self, graph: ImportGraph, verbose: bool) -> ContractCheck:
        # importlinter replaces each field on the instance with its parsed value.
        container: Module = self.container  # pyright: ignore[reportAssignmentType]
        separation = _Separation(graph, container.name)
        violations = [
            " -> ".join(chain)
            for query in sorted(graph.find_descendants(container.name))
            if separation.kind(query) == "queries"
            for chain in [separation.chain_to_command(query)]
            if chain
        ]
        return ContractCheck(kept=not violations, metadata={"violations": violations})

    @override
    def render_broken_contract(self, check: ContractCheck) -> None:
        assert check.metadata is not None, "check() always sets metadata"
        for violation in cast(list[str], check.metadata["violations"]):
            output.print_error(f"- {violation}")
        output.new_line()


class _Separation:
    def __init__(self, graph: ImportGraph, container: str) -> None:
        self._graph: ImportGraph = graph
        self._container: str = container
        self._features: set[str] = graph.find_children(container)
        root = find_spec(container.split(".")[0])
        assert root is not None and root.origin is not None, f"{container} is not importable"
        self._source_root: Path = Path(root.origin).parent.parent

    def kind(self, module: str) -> str | None:
        parts = module.removeprefix(f"{self._container}.").split(".")
        return parts[1] if module.startswith(f"{self._container}.") and len(parts) > 1 else None

    def chain_to_command(self, query: str) -> list[str] | None:
        previous: dict[str, str | None] = {query: None}
        queue = deque([query])
        while queue:
            module = queue.popleft()
            if self.kind(module) == "commands":
                chain = [module]
                while (step := previous[chain[-1]]) is not None:
                    chain.append(step)
                return chain[::-1]
            for target in sorted(self._targets(module) - previous.keys()):
                previous[target] = module
                queue.append(target)
        return None

    def _targets(self, module: str) -> set[str]:
        """The contexts modules `module` depends on, with a feature's top level resolved to the
        modules defining the names taken from it."""
        targets: set[str] = set()
        for imported in self._graph.find_modules_directly_imported_by(module):
            if imported in self._features and imported != module:
                names = self._names_taken(module, imported)
                exports = self._exports(imported)
                targets |= {exports.get(name, imported) for name in names} if names else {imported}
            elif imported.startswith(f"{self._container}."):
                targets.add(imported)
        return targets

    def _names_taken(self, module: str, feature: str) -> set[str]:
        """Names `module` takes from `feature`, or none when it takes the feature whole."""
        parent, _, last = feature.rpartition(".")
        tree = self._parse(module)
        names: set[str] = set()
        aliases: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == feature:
                names |= {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module == parent:
                aliases |= {
                    alias.asname or alias.name for alias in node.names if alias.name == last
                }
            elif isinstance(node, ast.Import) and any(a.name == feature for a in node.names):
                return set()
        return names | {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in aliases
        }

    def _exports(self, feature: str) -> dict[str, str]:
        return {
            alias.asname or alias.name: node.module
            for node in ast.walk(self._parse(feature))
            if isinstance(node, ast.ImportFrom) and node.module is not None
            for alias in node.names
        }

    def _parse(self, module: str) -> ast.Module:
        path = self._source_root.joinpath(*module.split("."))
        source = path / "__init__.py" if path.is_dir() else path.with_suffix(".py")
        return ast.parse(source.read_text())
