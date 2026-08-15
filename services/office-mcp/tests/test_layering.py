"""The structural rules this package's layout depends on.

**A tool is a file, and these are the rules that keep it one.** `tools/get_me.py` owns its name, the
prose that teaches a model when to reach for it, its Graph permissions, its arguments, its answer
shape, its request and its refusals. `shared/` is what a second tool will not be free to disagree
with it about. `graph_client/` is the transport they borrow. What follows is the whole of what that
costs, numbered as the finished layout numbers it — three of the eight rules cannot be asserted with
one tool and one shared module, and they are named below where they are missing rather than
renumbered around, so that the PR that makes one assertable adds a class and changes nothing else.

`features/`, which was to hold what a tool did, and the tool-declaration module `server/` was to
hold, are the shape this replaces; the first is deleted here and the second was never written. The
two numbered rules that held those halves apart went with them.

1. **`shared/` imports no tool module, and only `shared/seam.py` imports FastMCP.** `shared/` is
   what two tools must not disagree about; a tool is what disagrees. The direction is therefore
   one-way by construction. The FastMCP half is narrower than a blanket ban because it has to be:
   the On-Behalf-Of token dependency and the `ToolError` a Graph refusal becomes are exactly the
   things every tool must say identically, and they are FastMCP types. So they are allowed in one
   named file — the seam — and nowhere else, which is what keeps the framework out of the handle
   grammar, the message shape and the rest of the vocabulary.

2. **`graph_client/` imports nothing of this application.** Not `shared/`, not `tools/`, not
   `config`, not anything else under `office_mcp` — the transport is infrastructure its callers
   consume, and it takes its own frozen `GraphSettings` rather than reading config, because a
   transport is allowed to be *told* and not to be configured. Anything it imported back would be a
   package cycle and a second place the environment is read.

3. **`tools/` imports `shared/`, `graph_client/` and FastMCP, and nothing else of this package.**
   Those three are the whole of what a tool file is allowed to lean on: the vocabulary, the
   transport, the framework. Not `server/` — a tool that reached into it would be a tool file in
   name only, with its wiring somewhere else, which is the shape this layout exists to avoid.

4. **No tool module imports another tool module.** This is what "independent" means and it is the
   rule this whole layout exists for. Two tool files that shared a description constant, an error
   text or a helper would have re-created the tool-declaration module they exist instead of, one
   import at a time — and the failure is not abstract: the thing tools are most tempted to share is
   prose, and prose that is shared is prose that stops being about the tool it is on. If two of them
   genuinely need the same thing, it is shared vocabulary and belongs in `shared/`, where the fact
   that two tools depend on it is visible. `tools/__init__.py` is exempt and is the only exemption:
   it is the registry, its whole job is to know every module, and the union of their permissions
   could not be derived otherwise.

   **The package's own front door is not a way round it.** `from .. import tools` — or
   `from office_mcp import tools`, or either under an alias — never spells a sibling's name, and it
   does not have to: the registry imports every tool module, so the package object carries both of
   them as attributes and `tools.get_me.GRAPH_PERMISSIONS` is one line away. The module that import
   names is `office_mcp`, which is why a check that only resolved the module missed it entirely;
   what is matched is therefore the *member* as well, and a tool file that imports the package it
   lives in is reported like any other sibling import. What is deliberately not chased is
   `importlib.import_module("office_mcp.tools.get_me")` and its relatives — the same posture rule 6
   states: a tripwire rather than a barrier, catching the import somebody writes without thinking
   rather than the one somebody writes to hide.

5. **A config class is only instantiated at the composition root.** `create_app` builds each one
   exactly once and injects it; anything downstream constructing its own re-reads the environment
   and so silently ignores what it was given — which is how a tool ends up configured differently
   from the app it runs in. Reading config types (annotations, imports) is unrestricted; only
   *calling* them is the violation. `main.py` is exempt as a process entrypoint: it is the root of
   its own program and hands `create_app` the config it built.

6. **One speller per handle family: `shared/handles.py` alone spells or parses a `teams:///` URI.**
   A handle is how one tool's answer becomes another tool's argument, and that works only while
   there is one definition of each shape. Two modules that each knew how to write
   `teams:///chats/…` would be free to disagree, and the disagreement would not look like a
   disagreement — it would look like a handle one tool produced and another answers 404 to. The
   owner is named once for every family rather than per family, which is strictly stronger than
   letting each grammar live with the tool that mints it: three tools mint between them the four
   shapes below and no tool file spells one, so there is nothing for a second speller to be.

   *Spells or parses* is about what a literal is **used for**, not about how it is spaced. Prose is
   most of what the scheme is written in here and all of it is legitimate: a tool description shows
   a model the shapes it may pass, a JSON-schema `examples=` or `json_schema_extra` carries a real
   one so the model sees a genuine percent-encoded id, a one-line docstring is sometimes the shape
   itself — one line reading `teams:///meetings/{meeting_id}` and nothing else — and a refusal shows
   the shape again in a fragment short enough to have no whitespace at all. A spacing test forbids
   all four, and a rule that forbids the idiomatic thing is a rule somebody deletes.

   So a literal carrying the scheme is an **implementation** when something is *done* to it —
   concatenated with a value, `%`-formatted, `.format()`ed, `.join()`ed, handed to `re.*`, or handed
   to `startswith`/`endswith`/`removeprefix`/`removesuffix`/`split`/`partition` as the thing a URI
   is taken apart by — and **prose** when it merely sits there. An f-string counts as building when
   the interpolation is adjacent to the scheme's own path (`f"teams:///meetings/{x}"`), and a
   concatenation counts on the same adjacency (`"teams:///chats/" + chat_id`): a run that reaches
   the handover without whitespace is a handle being assembled, and one that wanders back into a
   sentence first is a paragraph being assembled. Regex syntax in the literal is still read as
   matching wherever it appears, because it never appears in prose a model reads.

   The scheme kept in a module constant — `_SCHEME = "teams:///"` — is caught at the **use** and
   never at the assignment. It cannot be the assignment: `_HINT = "teams:///meetings/..."` is
   character-for-character the same statement written for a refusal. So the name is remembered and
   the line reported is the one that builds or parses with it — `f"{_SCHEME}chats/{c}"`, or
   `_TEMPLATE.format(...)` — with the message naming the constant and the line it was bound on, so
   that "why is my constant a violation" is answered in the failure itself.

   **This is a text-level check, and it is a tripwire rather than a barrier.** What it cannot see is
   any module that never writes the scheme in one piece. One such module imports `handles.py`'s own
   constant and assembles a URI out of it — reaching for another module's private name is a
   violation of that module's surface before it is a violation of this one. The rest write the
   scheme in pieces: `"teams" + ":///" + "chats/" + c`, `"".join(("teams:", "//", "/chats/", c))`,
   `b"teams:///chats/".decode() + c`, `"teams" + chr(58) + "///chats/" + c`, and
   `"teams:///chats/\\n".strip() + c`. None of them is chased, deliberately — each extra pattern
   buys one contrived case and costs a rule that is harder to read and easier to trip by accident.
   The class of thing this catches is the second speller somebody writes without thinking, which is
   the one that actually happens; somebody determined to hide one succeeds.

8. **A package is entered through its `__init__`, never through its modules.** Applies to the
   packages in `_PUBLIC_SURFACE_PACKAGES`: `graph_client/`, `server/` and `tools/`, each of which
   publishes an `__all__` that is the whole of what it promises. Reaching past one means
   assembling collaborators the package is responsible for assembling — which is how a tool came
   to re-read its own config and ignore what `create_app` was given — and on `tools/` it is
   precisely how somebody imports `tools/get_me.py` directly and stops the registry being the one
   place every tool module is named — which is the list a selection is filtered over and every
   Graph scope sign-in asks for is derived from.

   `shared/` is deliberately not listed, because it publishes no surface. It is a grouping whose
   `__init__` is documentation and whose *modules* are the units — `shared/identity.py` is who the
   signed-in user is, `shared/seam.py` is how a tool is attached to the outside — and every consumer
   names which of them it depends on at the import line. That visibility is what the package is
   *for*, so an `__init__` re-exporting the lot would hide the one thing it exists to show. A
   package joins the list as soon as its `__init__` exports anything.

**Rules 4 and 6 arrive here, and rule 7 is still absent, for the same reason in both directions.**
Every rule here is paired with a guard that fails if the rule has stopped having anything to check —
an empty tree to walk, a missing file to forbid reaching past, a framework nothing imports any more,
a second tool module that stopped existing so that "another tool module" named nothing, a package
with no `__all__` to insist on — and the same discipline says a rule may not arrive before its guard
can pass. A rule that is written down while it forbids nothing is a rule that gets deleted for the
wrong reason later, or worse, kept while the thing it covers quietly leaves.

Rule 4 needed two tool modules to have anything to say and rule 6 needed a handle, and `list_chats`
is both: it is the second tool and the first whose answer carries a `teams:///` URI. So both are
asserted from here, each with the guard that would fail if it went back to forbidding nothing.

* **Rule 7, no module addresses a single meeting recording** — the permanent one, and the only door
  to a recording's bytes — needs a recordings listing to be the surface it protects. It arrives with
  the tool that lists them, and the numbering is left as the finished layout numbers it so that
  arriving costs a class and changes nothing else.

None of the rules that *are* here is conditional: every package they are about exists today, so a
rule that stops running is a failure and not a skip.

All rules are asserted by walking the AST rather than importing anything, so a violation is
reported as a failing test with a file and line instead of an ImportError at collection time.
"""

import ast
import pathlib
import re
import sys

import pytest

_SRC = pathlib.Path(__file__).parent.parent / "src" / "office_mcp"

_SHARED = _SRC / "shared"
_TOOLS = _SRC / "tools"
_GRAPH_CLIENT = _SRC / "graph_client"

_PACKAGE = "office_mcp"
_SHARED_PREFIX = "office_mcp.shared"
_TOOLS_PREFIX = "office_mcp.tools"
_SERVER_PREFIX = "office_mcp.server"
_CONFIG_MODULE = "office_mcp.config"
_GRAPH_CLIENT_PREFIX = "office_mcp.graph_client"
_MCP_FRAMEWORK = "fastmcp"

# Packages that publish a surface: outside code imports the package, never a module inside it.
# Tests are deliberately exempt — the rule walks `src` only — so the pieces a package composes stay
# directly testable without being callable from production code that should go through the front
# door. `shared/` is not here on purpose; see rule 8.
_PUBLIC_SURFACE_PACKAGES: tuple[str, ...] = (
    "office_mcp.graph_client",
    "office_mcp.server",
    "office_mcp.tools",
)

# The one file under `shared/` that is allowed to speak MCP, because being the seam is what it is
# for. Named rather than pattern-matched: the exemption is a decision about one file.
_SEAM = _SHARED / "seam.py"

# The scheme every handle this connector mints is written in, and the one module that may implement
# it. See rule 6 for why the check is on building and matching rather than on the text.
_HANDLE_SCHEME = "teams:///"
_HANDLE_OWNER = _SHARED / "handles.py"
_HANDLE_FAMILIES = frozenset({"chats", "teams", "meetings"})
_HANDLE_FAMILY = re.compile(re.escape(_HANDLE_SCHEME) + r"([A-Za-z_]*)")

# What tells a string that *matches* a handle from a string that *shows* one. Regex syntax never
# appears in prose a model reads, and prose is the only other reason to write the scheme.
_PATTERN_SYNTAX: tuple[str, ...] = (r"\A", r"\Z", "[^", "(?")

# The methods that make a scheme-carrying literal an implementation of the grammar. Building is a
# template being filled (`.format`) or segments being pasted (`.join`); parsing is a URI being taken
# apart by hand, which is what a second *reader* of the grammar looks like in the wild — written
# with string methods rather than with a regex, so the pattern-syntax check never sees it.
_BUILDING_METHODS = frozenset({"format", "join"})
_PARSING_METHODS = frozenset(
    {
        "startswith",
        "endswith",
        "removeprefix",
        "removesuffix",
        "split",
        "rsplit",
        "partition",
        "rpartition",
    }
)

# The module a handle handed to `re.compile`/`re.match`/`re.sub`/… is being matched by, whether or
# not the pattern happens to carry any of `_PATTERN_SYNTAX`.
_REGEX_MODULE = "re"

# Adjacency, not prose: where a literal run hands over to a value — an f-string interpolation or a
# concatenated expression — the text between the scheme and the handover decides what is being
# assembled. Reaching the handover without whitespace is a handle (`f"teams:///meetings/{x}"`,
# `"teams:///chats/" + chat_id`); wandering back into a sentence first is a paragraph. See rule 6.
_WHITESPACE = re.compile(r"\s")

# The `BaseSettings` classes in config.py, which read the environment when constructed.
_CONFIG_CLASSES = frozenset({"AppConfig", "DatabaseConfig", "EntraConfig", "SurfaceConfig"})

# Files allowed to construct one, relative to `_SRC`. Both are the root of a program: `app.py` is
# the composition root, and `main.py` is the server entrypoint that hands it its `AppConfig`.
_COMPOSITION_ROOTS = frozenset({"app.py", "main.py"})


def _sources(directory: pathlib.Path) -> list[pathlib.Path]:
    return sorted(directory.rglob("*.py"))


def _tool_modules() -> list[pathlib.Path]:
    """The tool files: everything under `tools/` except the registry that composes them."""
    return [source for source in _sources(_TOOLS) if source.name != "__init__.py"]


def _imported_modules(tree: ast.AST, package: str | None = None) -> list[tuple[str, int]]:
    """Every module name this file imports, with the line it's imported on.

    A relative import (`level > 0`) is resolved to an absolute dotted name against `package` —
    the importing file's own `__package__` — before it's reported. Without that resolution,
    `from ..server.readiness import ready_response` inside `tools/get_me.py` would never spell
    `server` at `level == 0` and would be invisible to every rule below. Without a `package`
    (the ad-hoc source snippets in `TestTheDetectionItself` below, which name no real file),
    relative imports are skipped: there is nothing to resolve them against.
    """
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module is not None:
                    found.append((node.module, node.lineno))
            elif package is not None:
                resolved = _resolved_import_target(package, node.level, node.module)
                if resolved is not None:
                    found.append((resolved, node.lineno))
    return found


def _imported_members(tree: ast.AST, package: str | None = None) -> list[tuple[str, int]]:
    """Every `from X import name`, as the module `name` would be if it is one, with its line.

    The blind spot this exists for: `from .. import tools as _tools` inside `shared/identity.py`
    imports the module `office_mcp` and binds the whole tool package under a name, so every tool
    module is an attribute of it and no rule above ever sees one. `from office_mcp import tools` is
    the same import spelled absolutely. Both are caught here, and under any alias, because the alias
    is the *binding* and `alias.name` is what was imported.

    Matched **exactly** by the rules that use this, never as a prefix: `from office_mcp.shared
    import identity` names a module of a package nothing forbids, and `from office_mcp.graph_client
    import graph_client_for` names a function rather than a module at all. Only a member that *is*
    the forbidden package is a violation of anything.
    """
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level == 0:
            base = node.module
        elif package is not None:
            base = _resolved_import_target(package, node.level, node.module)
        else:
            base = None
        if base is None:
            continue
        found.extend((f"{base}.{alias.name}", node.lineno) for alias in node.names)
    return found


def _resolved_import_target(package: str, level: int, module: str | None) -> str | None:
    """The absolute dotted module a relative import's `level`/`module` resolve to.

    Mirrors Python's own relative-import resolution: `level` dots walk up from `package` (the
    importing file's `__package__`) by `level - 1` components, and `module` — if the import
    names one (`from . import x` doesn't) — is appended beneath that. Returns `None` if the
    import walks above the top of the tree, which `ast` parses fine but Python raises
    `ImportError` for at runtime.
    """
    parts = package.split(".")
    remaining = len(parts) - (level - 1)
    if remaining < 0:
        return None
    base = parts[:remaining]
    if module:
        base = base + module.split(".")
    return ".".join(base) if base else None


def _dotted_module(source: pathlib.Path) -> str:
    """The dotted module name `source` would import as, e.g. `office_mcp.tools.get_me`.

    Found by anchoring on the `office_mcp` directory in `source`'s own path, rather than by
    relativizing against the module-level `_SRC` constant — so a temporary copy of the tree
    (as `TestTheDetectionItself` below uses to prove the escape is caught) resolves the same
    way the real `src/office_mcp` does.
    """
    parts = source.with_suffix("").parts
    module_parts = parts[parts.index("office_mcp") :]
    if module_parts[-1] == "__init__":
        module_parts = module_parts[:-1]
    return ".".join(module_parts)


def _package_of(source: pathlib.Path) -> str:
    """The value `__package__` has inside `source`, i.e. what its relative imports resolve against.

    For a plain module `foo/bar/baz.py` that's `foo.bar` — the package containing it. For
    `foo/bar/__init__.py` it's `foo.bar` itself, since the module IS the package there.
    """
    module = _dotted_module(source)
    if source.name == "__init__.py":
        return module
    return module.rsplit(".", 1)[0]


def _source_id(source: pathlib.Path) -> str:
    """Test id for one module: `tools/get_me.py`, not an absolute path."""
    return str(source.relative_to(_SRC))


def _reaches(tree: ast.AST, prefix: str, package: str | None = None) -> list[tuple[str, int]]:
    """Every import in `tree` that reaches `prefix`, by module or through the package's front door.

    Two questions, because there are two ways in. The module a file imports is `prefix` itself or
    something under it (`import office_mcp.tools`, `from office_mcp.tools.get_me import …`), or the
    file imports the package *as a member* of the package above it (`from .. import tools`), which
    names `prefix` nowhere and hands over every module inside it just the same. The second is
    matched exactly and the first by prefix — see `_imported_members` for why.
    """
    return [
        (module, line)
        for module, line in _imported_modules(tree, package)
        if module == prefix or module.startswith(f"{prefix}.")
    ] + [(member, line) for member, line in _imported_members(tree, package) if member == prefix]


def _imports_under(source: str, prefix: str, package: str | None = None) -> list[str]:
    """The `prefix`-rooted modules `source` imports. Every import rule below is this."""
    return [module for module, _line in _reaches(ast.parse(source), prefix, package)]


def _violations(source: pathlib.Path, prefix: str) -> list[str]:
    tree = ast.parse(source.read_text(), filename=str(source))
    return [
        f"{source.relative_to(_SRC)}:{line} imports {module}"
        for module, line in _reaches(tree, prefix, _package_of(source))
    ]


def _package_directory(package: str) -> pathlib.Path:
    """`office_mcp.graph_client` → the directory that package's modules live in."""
    return _SRC.joinpath(*package.split(".")[1:])


def _is_inside(directory: pathlib.Path, package: str) -> bool:
    return directory == _package_directory(package) or directory.is_relative_to(
        _package_directory(package)
    )


def _internal_imports(
    source: str, directory: pathlib.Path, package: str | None = None
) -> list[tuple[str, int]]:
    """Modules of a public-surface package that `source` reaches past the `__init__` for.

    A file inside a package may import its own package's modules freely — that is the package
    composing itself, and `tools/__init__.py` naming every tool module is the clearest case of
    it — so the directory the file lives in, not its name, decides.
    """
    return [
        (module, line)
        for surface in _PUBLIC_SURFACE_PACKAGES
        if not _is_inside(directory, surface)
        for module, line in _imported_modules(ast.parse(source), package)
        if module.startswith(f"{surface}.")
    ]


def _internal_module_violations(source: pathlib.Path) -> list[str]:
    reached = _internal_imports(source.read_text(), source.parent, _package_of(source))
    return [f"{source.relative_to(_SRC)}:{line} imports {module}" for module, line in reached]


def _declares_all(init: pathlib.Path) -> bool:
    """Whether `init` assigns an `__all__`, which is the front door it insists on being used."""
    return any(
        isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
        for node in ast.walk(ast.parse(init.read_text()))
    )


def _own_package_violations(source: pathlib.Path) -> list[str]:
    """Every import `source` makes of this application, whatever part of it."""
    return _violations(source, _PACKAGE)


def _config_constructions(source: str) -> list[tuple[str, int]]:
    """Calls in `source` that construct a config class, with the line each is on.

    Only calls count. Importing a config type, annotating a parameter with one, or handing one
    to `isinstance` are all how an injected config is *used*, and none of them read the
    environment. `AppConfig.model_validate({...})` is likewise left alone: it validates the data
    it is given rather than gathering its own.
    """
    found: list[tuple[str, int]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        called = node.func
        if isinstance(called, ast.Name) and called.id in _CONFIG_CLASSES:
            found.append((called.id, node.lineno))
        # `config.EntraConfig()` — the same construction reached through its module.
        elif isinstance(called, ast.Attribute) and called.attr in _CONFIG_CLASSES:
            found.append((called.attr, node.lineno))
    return found


def _config_construction_violations(source: pathlib.Path) -> list[str]:
    relative = source.relative_to(_SRC)
    if relative.as_posix() in _COMPOSITION_ROOTS:
        return []
    return [
        f"{relative}:{line} constructs {name}()"
        for name, line in _config_constructions(source.read_text())
    ]


def _handle_spellings(source: str) -> list[str]:
    """Where `source` spells or parses a `teams:///` URI, as opposed to showing one.

    The question asked of every scheme-carrying literal is what it is *used for*, not how it is
    spaced — see rule 6 for why a spacing test would not do. Four shapes, and between them they are
    what an implementation of the grammar looks like:

    * **Matching.** A string that carries the scheme *and* regex syntax, or one handed to `re.*`
      however it is written. Prose shows a shape; a pattern takes one apart.
    * **Building through a handover.** An f-string in which an interpolation follows the scheme's
      own path (`f"teams:///meetings/{segment}"`), or a concatenation that appends a value to it
      (`"teams:///chats/" + chat_id`). Both are checked on adjacency rather than on the sentence
      around them, because a description that interpolates a real id is a builder wearing prose's
      clothes — and, the other way round, a paragraph assembled with `+` from a line that happens
      to show a handle is not one.
    * **Building through a template.** `%`-formatting, `.format()` and `.join()`, where the URI is
      the template or a segment of it rather than something a value is pasted onto.
    * **Parsing by hand.** The literal handed to `startswith`, `removeprefix`, `split`, `partition`
      and their neighbours — a second *reader* of the grammar, which is what a second speller
      actually looks like in the wild.

    A name bound to a scheme-carrying literal is the same thing one step earlier, so it is followed:
    `_SCHEME = "teams:///"` is caught where it is built with and never where it is assigned, because
    the assignment is indistinguishable from a refusal's `_HINT = "teams:///meetings/..."`.

    Everything else is prose and is left alone: a description, an `examples=` list, a
    `json_schema_extra` example, a docstring that is the shape itself, a refusal fragment, or a
    constant nobody builds with.

    The literal runs inside an f-string are left to the building check, which is the only reason
    to write an f-string; judging them separately would report the owner's own lines twice.
    """
    tree = ast.parse(source)
    parents = _parents(tree)
    bound = _scheme_bindings(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            found.extend(f"line {node.lineno} builds a handle" for _ in _built_handles(node))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _HANDLE_SCHEME not in node.value or isinstance(parents.get(id(node)), ast.JoinedStr):
                continue
            if any(syntax in node.value for syntax in _PATTERN_SYNTAX):
                found.append(f"line {node.lineno} matches a handle")
                continue
            use = _use_made_of(node, parents, adjacency=node.value)
            if use is not None:
                found.append(f"line {node.lineno} {use} a handle")
        elif isinstance(node, ast.Name) and node.id in bound and isinstance(node.ctx, ast.Load):
            use = _use_made_of(node, parents, adjacency=None)
            if use is not None:
                found.append(
                    f"line {node.lineno} {use} a handle through {node.id} "
                    + f"(bound on line {bound[node.id]})"
                )
    return found


def _parents(tree: ast.AST) -> dict[int, ast.AST]:
    """Each node's parent, by `id`. What a literal is used for is a question about its parent."""
    return {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _scheme_bindings(tree: ast.AST) -> dict[str, int]:
    """Names assigned a scheme-carrying literal, and the line each was bound on.

    The binding is not the violation and is never reported as one — `_HINT = "teams:///..."` is a
    refusal, `_SCHEME = "teams:///"` is a grammar's root, and the two are the same statement. This
    is what lets the *use* of either be judged like the literal itself.
    """
    bound: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        value = node.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        if _HANDLE_SCHEME not in value.value:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                bound.setdefault(target.id, node.lineno)
    return bound


def _use_made_of(
    node: ast.expr, parents: dict[int, ast.AST], *, adjacency: str | None
) -> str | None:
    """What `node`'s surroundings do with the URI it carries: build it, match it, or nothing.

    `adjacency` is the literal's own text where there is one, and None for a name — a concatenation
    is judged on whether the run reaches the handover without whitespace, and a name bound to the
    scheme has no run to judge, so `+` on one is left alone (that is how a refusal's hint constant
    goes on being concatenated with more prose).
    """
    parent = parents.get(id(node))
    if isinstance(parent, ast.FormattedValue):
        return "builds"
    if isinstance(parent, ast.BinOp):
        if isinstance(parent.op, ast.Mod):
            return "spells"
        if isinstance(parent.op, ast.Add) and adjacency is not None:
            other = parent.right if parent.left is node else parent.left
            hands_over = not _is_literal_text(other)
            reaches_it = not _WHITESPACE.search(adjacency.rsplit(_HANDLE_SCHEME, 1)[1])
            return "spells" if hands_over and reaches_it else None
        return None
    if isinstance(parent, ast.Attribute):
        return "spells" if parent.attr in _BUILDING_METHODS else None
    if isinstance(parent, ast.Call) and isinstance(parent.func, ast.Attribute):
        called = parent.func
        if called.attr in _PARSING_METHODS or called.attr in _BUILDING_METHODS:
            return "spells"
        if isinstance(called.value, ast.Name) and called.value.id == _REGEX_MODULE:
            return "matches"
        return None
    if isinstance(parent, ast.List | ast.Tuple | ast.Set):
        # `"/".join(("teams:///chats", chat_id))` — a segment handed to a joiner.
        joined = parents.get(id(parent))
        return (
            "spells"
            if isinstance(joined, ast.Call)
            and isinstance(joined.func, ast.Attribute)
            and joined.func.attr in _BUILDING_METHODS
            else None
        )
    return None


def _is_literal_text(node: ast.expr) -> bool:
    """Whether `node` is text known at parse time, i.e. prose rather than a value handed over.

    A chain of `+`-ed string literals is how a long description is written in this codebase, so the
    whole chain has to read as one literal — otherwise every paragraph that shows a handle on its
    own line would look like a concatenation building one.
    """
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _is_literal_text(node.left) and _is_literal_text(node.right)
    return False


def _built_handles(node: ast.JoinedStr) -> list[ast.Constant]:
    """The literal runs of `node` ending in the scheme's path that hand over to an interpolation."""
    parts = node.values
    return [
        part
        for index, part in enumerate(parts)
        if isinstance(part, ast.Constant)
        and isinstance(part.value, str)
        and _HANDLE_SCHEME in part.value
        and index + 1 < len(parts)
        and isinstance(parts[index + 1], ast.FormattedValue)
        and not _WHITESPACE.search(part.value.rsplit(_HANDLE_SCHEME, 1)[1])
    ]


def _handle_violations(source: pathlib.Path) -> list[str]:
    return [
        f"{source.relative_to(_SRC)} {spelling}"
        for spelling in _handle_spellings(source.read_text())
    ]


def _registry_imports() -> set[str]:
    """The tool modules `tools/__init__.py` names, by module stem.

    Both spellings, because either is how a module gets into `_TOOL_MODULES`: the names of a
    `from office_mcp.tools import get_me, list_chats`, and the tail of an
    `import office_mcp.tools.get_me`.
    """
    tree = ast.parse((_TOOLS / "__init__.py").read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module == _TOOLS_PREFIX or node.level == 1):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            found.update(
                alias.name.rsplit(".", 1)[-1]
                for alias in node.names
                if alias.name.startswith(f"{_TOOLS_PREFIX}.")
            )
    return found


def _a_tool_file_containing(
    source: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> pathlib.Path:
    """`tools/list_chats.py` in a throwaway copy of the tree, holding `source`.

    On disk rather than as a string because a relative import only resolves against a real package:
    `from .. import tools` is `office_mcp` seen from `office_mcp.tools.list_chats`, and nothing but
    the file's own path says which. `_SRC` is repointed at the copy so the violation comes back
    named the way the real rules name one.
    """
    module = tmp_path / "office_mcp" / "tools" / "list_chats.py"
    module.parent.mkdir(parents=True)
    module.write_text(source)
    monkeypatch.setattr(sys.modules[__name__], "_SRC", tmp_path / "office_mcp")
    return module


class TestTheDetectionItself:
    """The rules are only worth having if they fail on the things they're meant to catch."""

    def test_catches_the_violation_the_shared_rule_exists_for(self) -> None:
        assert _imports_under(
            "from office_mcp.tools.get_me import SignedInUser", _TOOLS_PREFIX
        ) == ["office_mcp.tools.get_me"]

    def test_catches_a_plain_import_too(self) -> None:
        assert _imports_under("import office_mcp.tools.get_me", _TOOLS_PREFIX) == [
            "office_mcp.tools.get_me"
        ]

    def test_catches_a_relative_import_that_escapes_the_layer(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`from ..tools.get_me import SignedInUser` inside `shared/identity.py` never spells
        `tools` at `level == 0`, so a level-blind check is silently invisible to exactly the
        violation rule 1 exists to catch. Proves the fix against the real checker (`_violations`,
        what the rules below run) over an actual file on disk.
        """
        src = tmp_path / "office_mcp"
        module = src / "shared" / "identity.py"
        module.parent.mkdir(parents=True)
        module.write_text("from ..tools.get_me import SignedInUser\n")
        monkeypatch.setattr(sys.modules[__name__], "_SRC", src)

        assert _violations(module, _TOOLS_PREFIX) == [
            "shared/identity.py:1 imports office_mcp.tools.get_me"
        ]

    def test_catches_a_tool_reaching_its_siblings_through_the_front_door(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The escape rule 4 would have without this check: the registry imports every tool module,
        so the package object carries both of them as attributes and one import of it is
        `tools.get_me.GRAPH_PERMISSIONS`. The module imported is `office_mcp` — no sibling's name
        appears anywhere — which is why resolving the module alone never sees it.
        """
        module = _a_tool_file_containing("from .. import tools\n", tmp_path, monkeypatch)

        assert _violations(module, _TOOLS_PREFIX) == [
            "tools/list_chats.py:1 imports office_mcp.tools"
        ]

    def test_catches_the_same_reach_spelled_absolutely(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`from office_mcp import tools` is the same package bound the same way, and the module it
        names is the same `office_mcp` — the dots are the only difference."""
        module = _a_tool_file_containing("from office_mcp import tools\n", tmp_path, monkeypatch)

        assert _violations(module, _TOOLS_PREFIX) == [
            "tools/list_chats.py:1 imports office_mcp.tools"
        ]

    def test_catches_it_under_an_alias(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An alias renames the binding and not the import, and the private-looking name is what a
        tool file would actually be written with."""
        module = _a_tool_file_containing(
            "from .. import tools as _siblings\n"
            + "PERMISSIONS = _siblings.get_me.GRAPH_PERMISSIONS\n",
            tmp_path,
            monkeypatch,
        )

        assert _violations(module, _TOOLS_PREFIX) == [
            "tools/list_chats.py:1 imports office_mcp.tools"
        ]

    def test_catches_it_inside_a_function_body(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Where a sibling import is likeliest to be written, since deferring it is how somebody
        gets round the circular import a module-level one would cause. The walk is over the whole
        tree, so the line reported is the import's own."""
        module = _a_tool_file_containing(
            "def register(mcp: object, transport: object) -> tuple[str, ...]:\n"
            + "    from office_mcp import tools\n"
            + "    return tools.get_me.GRAPH_PERMISSIONS\n",
            tmp_path,
            monkeypatch,
        )

        assert _violations(module, _TOOLS_PREFIX) == [
            "tools/list_chats.py:2 imports office_mcp.tools"
        ]

    def test_does_not_fire_on_a_member_that_is_not_the_package(self) -> None:
        """The negative control for the member check, and the reason it matches exactly rather than
        by prefix: `from office_mcp.shared import identity` names a module of a package no rule
        forbids, and `from office_mcp.graph_client import graph_client_for` names a function. A
        prefix match on members would make rule 8 fire on both."""
        assert not _imports_under(
            "from office_mcp.shared import identity, seam\n"
            + "from office_mcp.graph_client import graph_client_for\n",
            _TOOLS_PREFIX,
        )
        assert not _internal_imports("from office_mcp.graph_client import graph_client_for\n", _SRC)

    def test_catches_the_violation_the_mcp_framework_rule_exists_for(self) -> None:
        assert _imports_under(
            "from fastmcp.exceptions import ToolError\nimport fastmcp\n", _MCP_FRAMEWORK
        ) == ["fastmcp.exceptions", "fastmcp"]

    def test_the_mcp_framework_rule_leaves_the_protocol_types_alone(self) -> None:
        """`mcp` is the protocol SDK, a different distribution from the server framework, and a
        name that merely begins with `fastmcp` is not it either."""
        assert not _imports_under(
            "from mcp.types import TextContent\nfrom fastmcpx import thing", _MCP_FRAMEWORK
        )

    def test_catches_the_violation_the_transport_rule_exists_for(self) -> None:
        """Anything of this application at all, not only the three named packages: the transport
        takes settings and a token and knows nothing else."""
        assert _imports_under(
            "from office_mcp.shared.identity import PROFILE\n"
            + "from office_mcp.config import AppConfig\n"
            + "from office_mcp.server import ready_response\n",
            _PACKAGE,
        ) == ["office_mcp.shared.identity", "office_mcp.config", "office_mcp.server"]

    def test_the_transport_rule_leaves_the_sdk_and_its_own_modules_alone(self) -> None:
        """`graph_client` composing itself is the package doing its job, and `msgraph` is what it
        is *for*."""
        assert not [
            module
            for module in _imports_under(
                "from office_mcp.graph_client.settings import GraphSettings\n"
                + "from msgraph.graph_service_client import GraphServiceClient\n",
                _PACKAGE,
            )
            if not module.startswith(_GRAPH_CLIENT_PREFIX)
        ]

    def test_catches_a_tool_reaching_into_the_layer_that_exposes_it(self) -> None:
        assert _imports_under(
            "from office_mcp.server import ready_response\n"
            + "from office_mcp.server.readiness import ready_response\n",
            _SERVER_PREFIX,
        ) == ["office_mcp.server", "office_mcp.server.readiness"]

    def test_does_not_fire_on_permitted_imports(self) -> None:
        """The negative control, and the one that keeps every rule above from being a rule
        against importing anything: each is one call to `_imports_under`, so a helper that
        matched loosely would turn "a tool imports only shared/, graph_client/ and FastMCP" into
        "a tool imports nothing" and every rule would pass by forbidding the whole language.
        These three are exactly what rule 3 permits a tool file, plus a cross-cutting module.
        """
        assert not _imports_under(
            "from office_mcp.shared.identity import PROFILE\n"
            + "from office_mcp.graph_client import graph_client_for\n"
            + "from office_mcp.logging import configure_logging\n"
            + "from fastmcp import FastMCP\n",
            _TOOLS_PREFIX,
        )

    def test_catches_the_violation_the_internals_rule_exists_for(self) -> None:
        # `server` stands in for any listed package here; the rule is about the front door, not
        # about which package happens to be behind it. The importing directory is `_SRC` — i.e.
        # `app.py`, the composition root, which is the likeliest place to reach past one.
        reached = _internal_imports("from office_mcp.server.readiness import ready_response", _SRC)

        assert reached == [("office_mcp.server.readiness", 1)]

    def test_catches_reaching_past_the_registry_for_a_tool_file(self) -> None:
        """The case rule 8 gained with `tools/`: importing a tool module directly is how the
        registry stops being the one place every tool is named, and both what a selection is
        filtered over and what sign-in asks for are derived from exactly that list."""
        assert _internal_imports("from office_mcp.tools.get_me import register", _SRC) == [
            ("office_mcp.tools.get_me", 1)
        ]

    def test_the_same_import_is_fine_inside_the_package(self) -> None:
        assert not _internal_imports(
            "from office_mcp.tools import get_me",
            _package_directory("office_mcp.tools"),
        )

    def test_does_not_fire_on_the_package_root(self) -> None:
        assert not _internal_imports(
            "from office_mcp.tools import register_tools, resolve\n"
            + "from office_mcp.server import ready_response, surface_manifest\n"
            + "from office_mcp.graph_client import create_graph_transport\n"
            + "from office_mcp.shared.identity import PROFILE\n",
            _SRC,
        )

    def test_catches_the_violation_the_config_construction_rule_exists_for(self) -> None:
        assert _config_constructions(
            "def graph_settings() -> None:\n    entra = EntraConfig()\n"
        ) == [("EntraConfig", 2)]

    def test_catches_a_config_built_through_its_module_too(self) -> None:
        assert _config_constructions("cfg = config.AppConfig()") == [("AppConfig", 1)]

    def test_does_not_fire_on_using_an_injected_config(self) -> None:
        assert not _config_constructions(
            "from office_mcp.config import EntraConfig\n"
            + "def build_auth(entra: EntraConfig) -> str:\n"
            + "    return entra.client_id\n"
        )

    def test_does_not_fire_on_validating_supplied_data(self) -> None:
        """`model_validate` is handed its values; it does not go looking for them."""
        assert not _config_constructions("AppConfig.model_validate({'port': 1})")

    def test_catches_a_handle_being_built(self) -> None:
        """The exact line someone writes when a second module finds it easier to assemble a URI
        than to import the type that owns one."""
        assert _handle_spellings(
            "def uri(chat_id: str, message_id: str) -> str:\n"
            + '    return f"teams:///chats/{chat_id}/messages/{message_id}"\n'
        ) == ["line 2 builds a handle"]

    def test_catches_a_handle_being_matched(self) -> None:
        assert _handle_spellings(
            '_CHAT = re.compile(r"\\Ateams:///chats/([^/]+)/messages/([^/]+)\\Z")\n'
        ) == ["line 1 matches a handle"]

    def test_catches_a_handle_assembled_by_concatenation(self) -> None:
        """Same duplication, a different AST — and the f-string check alone never sees it."""
        assert _handle_spellings(
            "def uri(chat_id: str, message_id: str) -> str:\n"
            + '    return "teams:///chats/" + chat_id + "/messages/" + message_id\n'
        ) == ["line 2 spells a handle"]

    def test_catches_a_handle_assembled_with_format(self) -> None:
        """Including the named-placeholder form, which is character-for-character what a
        description shows a model — the difference is that this one is a template rather than a
        sentence, and `.format` is what it is for. Reported at the `.format`, not at the
        assignment: the assignment on its own is indistinguishable from a refusal's hint.
        """
        assert _handle_spellings(
            '_TEMPLATE = "teams:///chats/{chat_id}/messages/{message_id}"\n'
            + "def uri(chat: str, message: str) -> str:\n"
            + "    return _TEMPLATE.format(chat_id=chat, message_id=message)\n"
        ) == ["line 3 spells a handle through _TEMPLATE (bound on line 1)"]

    def test_catches_a_handle_assembled_with_join(self) -> None:
        assert _handle_spellings(
            "def uri(chat_id: str, message_id: str) -> str:\n"
            + '    return "/".join(("teams:///chats", chat_id, "messages", message_id))\n'
        ) == ["line 2 spells a handle"]

    def test_catches_a_handle_assembled_with_percent_formatting(self) -> None:
        assert _handle_spellings(
            "def uri(chat_id: str, message_id: str) -> str:\n"
            + '    return "teams:///chats/%s/messages/%s" % (chat_id, message_id)\n'
        ) == ["line 2 spells a handle"]

    def test_catches_an_f_string_that_reaches_the_scheme_through_a_constant(self) -> None:
        """No literal in the f-string carries the scheme, so the building check cannot see this
        one. What gives it away is the constant being *built with*: the assignment is not the
        violation and is never reported as one — see the prose tests below, where the same
        statement is a refusal's hint — so the line reported is the f-string, and the message says
        which constant it reached the scheme through."""
        assert _handle_spellings(
            '_SCHEME = "teams:///"\n'
            + "def uri(chat_id: str) -> str:\n"
            + '    return f"{_SCHEME}chats/{chat_id}"\n'
        ) == ["line 3 builds a handle through _SCHEME (bound on line 1)"]

    def test_catches_a_hand_rolled_parser(self) -> None:
        """The one that matters most: a second *reader* of the grammar is what a second speller
        actually looks like in the wild, and it is written with string methods rather than with
        a regex — so the pattern-syntax check would never have fired on it."""
        found = _handle_spellings(
            "def parse(uri: str) -> tuple[str, str] | None:\n"
            + '    if not uri.startswith("teams:///"):\n'
            + "        return None\n"
            + '    chat, _, message = uri.removeprefix("teams:///chats/").partition("/messages/")\n'
            + "    return chat, message\n"
        )

        # Sorted rather than in source order: the walk is breadth-first, so two literals at
        # different depths come out in the tree's order and not the file's.
        assert sorted(found) == ["line 2 spells a handle", "line 4 spells a handle"]

    def test_leaves_a_handle_shown_to_a_model_alone(self) -> None:
        """Every description that teaches a shape, every refusal that shows one, and every
        docstring that names the scheme — including the ones inside an f-string, where the
        braces are escaped and the placeholders are text, and the one where the example is a
        real percent-encoded id rather than a placeholder at all. This is the property the
        text-level check has to keep: prose is most of what the scheme is written in here.
        """
        assert not _handle_spellings(
            '"""The `teams:///` grammar: every shape this connector mints."""\n'
            + '_BAD = "A readable handle looks like teams:///chats/{chat_id}/messages/{id}."\n'
            + '_SEEN = "e.g. teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000 — "\n'
            + '_ELSE = "a teams:///transcripts/... handle is not one this connector reads"\n'
            + '_DESC = f"""Pass teams:///transcripts/{{meeting_id}}/{{transcript_id}}, up to'
            + ' {MAX_TURNS} turns."""\n'
        )

    def test_leaves_a_schema_example_alone(self) -> None:
        """`examples=` is the idiomatic JSON-schema way to show a model a real handle, and a real
        handle has a percent-encoded id in it and no whitespace anywhere. Every tool file still to
        be written wants this, which is why a rule that forbade it would be a rule somebody deleted
        rather than obeyed."""
        assert not _handle_spellings(
            "uri: str = Field(\n"
            + '    description="The message to read.",\n'
            + '    examples=["teams:///chats/19%3Aabc%40thread.v2/messages/1700000000000"],\n'
            + ")\n"
        )

    def test_leaves_a_json_schema_extra_example_alone(self) -> None:
        """The same example carried the other way, which is what a schema keyword the model needs
        but pydantic does not model looks like."""
        assert not _handle_spellings(
            'uri: str = Field(json_schema_extra={"example": "teams:///transcripts/AAA/BBB"})\n'
        )

    def test_leaves_a_docstring_that_is_the_shape_alone(self) -> None:
        """A one-line docstring that IS the shape: no sentence around it, no whitespace in it, and
        nothing whatever done with it."""
        assert not _handle_spellings(
            "def meeting_uri(meeting_id: str) -> str:\n"
            + '    """teams:///meetings/{meeting_id}"""\n'
            + "    return _handle(meeting_id)\n"
        )

    def test_leaves_a_refusal_fragment_alone(self) -> None:
        """A refusal quoting a family, as a bare token because that is how it reads in a sentence —
        and the same statement as `_SCHEME = "teams:///"`, which is why the binding can never be
        the violation and the *use* is what is judged. Concatenating it with more prose is still
        prose."""
        assert not _handle_spellings(
            '_HINT = "teams:///meetings/..."\n'
            + "def refuse() -> str:\n"
            + '    return _HINT + " is the shape this tool takes"\n'
        )

    def test_does_not_fire_on_a_name_that_merely_starts_with_the_prefix(self) -> None:
        assert not _imports_under("from office_mcp.toolsmith import thing", _TOOLS_PREFIX)
        assert not _imports_under("from office_mcp.sharedish import thing", _SHARED_PREFIX)
        assert not _imports_under("from office_mcp.configuration import thing", _CONFIG_MODULE)


class TestSharedIsUpstreamOfEveryTool:
    def test_the_shared_tree_is_actually_there(self) -> None:
        """Guards the guard: the rule is parametrized over `shared/`, so an empty tree makes it
        zero tests that pass by not existing."""
        modules = [source for source in _sources(_SHARED) if source.name != "__init__.py"]
        assert modules, f"no shared modules found under {_SHARED}"

    @pytest.mark.parametrize("source", _sources(_SHARED), ids=_source_id)
    def test_no_shared_module_imports_a_tool(self, source: pathlib.Path) -> None:
        violations = _violations(source, _TOOLS_PREFIX)
        assert not violations, (
            "shared/ must not import tools/ — it is what tools must not disagree about, and a "
            + "tool is what disagrees. Whatever the tool has that shared/ needs is either the "
            + "tool's own (leave it there and pass the value in) or shared vocabulary (move it "
            + "here):\n  "
            + "\n  ".join(violations)
        )


class TestOnlyTheSeamSpeaksMcp:
    def test_the_seam_actually_speaks_it(self) -> None:
        """Guards the guard from both sides: if `seam.py` stopped importing FastMCP the exemption
        would be a dead letter, and if the file were renamed the rule would forbid the framework
        everywhere under `shared/` — including from the one file whose job it is."""
        assert _SEAM.is_file(), f"no such file: {_SEAM}"
        assert _imports_under(_SEAM.read_text(), _MCP_FRAMEWORK, _package_of(_SEAM)), (
            f"{_SEAM.name} no longer imports FastMCP, so it is no longer the seam"
        )

    @pytest.mark.parametrize("source", [s for s in _sources(_SHARED) if s != _SEAM], ids=_source_id)
    def test_no_other_shared_module_imports_the_mcp_framework(self, source: pathlib.Path) -> None:
        violations = _violations(source, _MCP_FRAMEWORK)
        assert not violations, (
            "only shared/seam.py may import FastMCP — the rest of the shared vocabulary answers "
            + "with its own types and raises Graph failures, and turning either into something an "
            + "MCP client sees is the seam's job or the tool's. Return the fact (or raise) and let "
            + "the tool decide what to say:\n  "
            + "\n  ".join(violations)
        )


class TestTheTransportImportsNothingOfThisApplication:
    def test_the_client_tree_and_its_own_settings_are_actually_there(self) -> None:
        """Guards the guard: without somewhere to put settings, the config half is unsatisfiable,
        and without modules there is nothing to walk."""
        sources = _sources(_GRAPH_CLIENT)
        assert sources, f"no python sources found under {_GRAPH_CLIENT}"
        assert {"client.py", "settings.py"} <= {source.name for source in sources}

    @pytest.mark.parametrize("source", _sources(_GRAPH_CLIENT), ids=_source_id)
    def test_no_client_module_imports_anything_of_ours(self, source: pathlib.Path) -> None:
        violations = [
            violation
            for violation in _own_package_violations(source)
            if _GRAPH_CLIENT_PREFIX not in violation
        ]
        assert not violations, (
            "graph_client/ must import nothing of this application — it is infrastructure its "
            + "callers consume, and it takes its own frozen settings from graph_client/settings.py "
            + "rather than reading config. Add the field to those settings and map it in "
            + "create_app, or put the shared type here (a Protocol, if the caller owns the "
            + "implementation):\n  "
            + "\n  ".join(violations)
        )


class TestAToolLeansOnlyOnSharedAndTheTransport:
    def test_a_tool_actually_imports_all_three(self) -> None:
        """Guards the guard: rule 3 is permissive, so what makes it a rule rather than a sentence
        is that the three permitted dependencies are genuinely used — if `tools/` stopped reaching
        for `shared/`, the vocabulary would have been copied into the tool files instead."""
        sources = _tool_modules()
        assert sources, f"no tool modules found under {_TOOLS}"
        for prefix in (_SHARED_PREFIX, _GRAPH_CLIENT_PREFIX, _MCP_FRAMEWORK):
            used = [
                module
                for source in sources
                for module in _imports_under(source.read_text(), prefix, _package_of(source))
            ]
            assert used, f"no tool module imports {prefix}"

    @pytest.mark.parametrize("source", _sources(_TOOLS), ids=_source_id)
    def test_no_tool_module_imports_the_layer_that_exposes_it(self, source: pathlib.Path) -> None:
        violations = _violations(source, _SERVER_PREFIX)
        assert not violations, (
            "a tool file must not import server/ — that is the shape it exists instead of, and a "
            + "tool that reaches into it has its wiring somewhere other than in itself. Bring it "
            + "into this file, and put anything a second tool needs into shared/:\n  "
            + "\n  ".join(violations)
        )


class TestNoToolKnowsAboutAnotherTool:
    def test_there_is_more_than_one_tool_to_confuse(self) -> None:
        """Guards the guard: "no tool module imports another" says nothing about a package holding
        one file. It also pins the registry as the only importer of them all — if it stopped
        importing every module, the union of their permissions would have come from somewhere
        else, which is the failure `tools/__init__.py` exists to prevent."""
        modules = _tool_modules()
        assert len(modules) > 1, f"fewer than two tool modules under {_TOOLS}"
        imported = _registry_imports()
        missing = sorted({source.stem for source in modules} - imported)
        assert not missing, (
            "tools/__init__.py must import every tool module — the Graph scopes sign-in asks for "
            + "are derived from them, so one it does not name is a tool whose permission never "
            + f"reaches the consent screen (missing {missing})"
        )

    @pytest.mark.parametrize("source", _tool_modules(), ids=_source_id)
    def test_no_tool_module_imports_another_tool_module(self, source: pathlib.Path) -> None:
        own = _dotted_module(source)
        violations = [
            violation
            for violation in _violations(source, _TOOLS_PREFIX)
            if f"imports {own}" not in violation
        ]
        assert not violations, (
            "a tool file must not import another tool file — that is what independent means, and "
            + "it is the rule this whole layout exists for. What two tools need is shared "
            + "vocabulary and belongs in shared/, where the fact that two of them depend on it is "
            + "visible; what one tool needs stays in that tool. A description, an error text or a "
            + "helper borrowed across is how a tool-declaration module grows back:\n  "
            + "\n  ".join(violations)
        )


class TestEachHandleFamilyHasOneHome:
    def test_the_owner_actually_writes_every_family(self) -> None:
        """Guards the guard: if a family stopped being minted where the rule says it is, the rule
        would forbid something nothing does and the grammar would have quietly moved."""
        assert _HANDLE_OWNER.is_file(), f"no such file: {_HANDLE_OWNER}"
        # A bare `teams:///` with no family after it is the docstring naming the scheme itself.
        families: list[str] = _HANDLE_FAMILY.findall(_HANDLE_OWNER.read_text())
        written = {family for family in families if family}

        assert written == _HANDLE_FAMILIES, (
            f"{_HANDLE_OWNER.name} spells the handle families {sorted(written)}, and rule 6 gives "
            + f"it {sorted(_HANDLE_FAMILIES)}"
        )

    def test_the_owner_both_builds_and_matches_them(self) -> None:
        """And guards it from the other side: the rule forbids two implementations, so the one it
        permits has to be an implementation — if `handles.py` stopped building or stopped parsing,
        somebody else would be doing it."""
        spellings = _handle_spellings(_HANDLE_OWNER.read_text())

        assert any("builds" in spelling for spelling in spellings), (
            f"{_HANDLE_OWNER.name} no longer builds a handle"
        )
        assert any("matches" in spelling for spelling in spellings), (
            f"{_HANDLE_OWNER.name} no longer parses a handle"
        )

    @pytest.mark.parametrize(
        "source", [s for s in _sources(_SRC) if s != _HANDLE_OWNER], ids=_source_id
    )
    def test_no_other_module_builds_or_parses_a_handle(self, source: pathlib.Path) -> None:
        violations = _handle_violations(source)
        assert not violations, (
            "shared/handles.py is the only module that may build or parse a teams:/// URI — a "
            + "second speller is free to disagree with it, and the disagreement looks like a "
            + "handle one tool produced and another cannot read. Build that module's handle type "
            + "and read its `uri`, or call its parser. What is caught here is a literal something "
            + "is DONE to: concatenated with a value, %-formatted, .format()ed, .join()ed, matched "
            + "with re.*, or taken apart with startswith/removeprefix/split/partition — and, where "
            + "the report names a constant, the line that builds or parses with it rather than the "
            + "line that bound it. Showing the shape to a model is prose and is not this: a "
            + "description, an `examples=`, a `json_schema_extra` example, a docstring that is the "
            + "shape, and a refusal that quotes it are all left alone:\n  "
            + "\n  ".join(violations)
        )


class TestPackagesAreEnteredThroughTheirInit:
    """Rule 8."""

    @pytest.mark.parametrize("package", _PUBLIC_SURFACE_PACKAGES)
    def test_every_listed_package_actually_publishes_something(self, package: str) -> None:
        """Guards the guard: a package with no `__all__` has no front door to insist on."""
        init = _package_directory(package) / "__init__.py"
        assert init.is_file(), f"no __init__.py for {package}"
        assert _declares_all(init), f"{package}/__init__.py declares no __all__"

    @pytest.mark.parametrize("source", _sources(_SRC), ids=_source_id)
    def test_no_module_reaches_past_another_packages_init(self, source: pathlib.Path) -> None:
        violations = _internal_module_violations(source)
        assert not violations, (
            "import the package, not a module inside it — a package's __all__ is the whole of "
            + "what it promises, and reaching past it means assembling collaborators the package "
            + "is responsible for assembling (which is how a tool came to re-read its own config "
            + "and ignore what create_app was given). Export the name from that package's "
            + "__init__ and import it from there:\n  "
            + "\n  ".join(violations)
        )


class TestConfigIsBuiltOnlyAtTheCompositionRoot:
    def test_every_exempt_file_actually_exists(self) -> None:
        """Guards the guard: a renamed entrypoint would silently widen the exemption."""
        for relative in sorted(_COMPOSITION_ROOTS):
            assert (_SRC / relative).is_file(), f"no such file: {relative}"

    def test_the_composition_root_really_does_build_every_config(self) -> None:
        """And guards it from the other side: if `app.py` stopped constructing the config
        classes, they would be built somewhere else and this rule would be vacuous."""
        built = {name for name, _line in _config_constructions((_SRC / "app.py").read_text())}

        assert built >= _CONFIG_CLASSES, f"app.py does not build {_CONFIG_CLASSES - built}"

    @pytest.mark.parametrize("source", _sources(_SRC), ids=_source_id)
    def test_no_module_outside_the_root_builds_its_own_config(self, source: pathlib.Path) -> None:
        violations = _config_construction_violations(source)
        assert not violations, (
            "only create_app() may construct a config — building one here re-reads the "
            + "environment and quietly ignores whatever create_app was given. Take the value "
            + "as a parameter and let the composition root pass it in:\n  "
            + "\n  ".join(violations)
        )
