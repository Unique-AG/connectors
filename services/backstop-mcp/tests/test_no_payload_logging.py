"""No log or span call may carry a whole payload.

The walk is syntactic. A value passed under an innocent name is invisible here; the runtime
canary in `tests/test_no_payload_in_telemetry.py` covers that. Entries in `_KNOWN_VIOLATIONS`
are the leaks that exist today. Phase 6 removes them, and the second test fails if an entry
is left behind after the call it names is gone.
"""

import ast
import pathlib

_SRC = pathlib.Path(__file__).parent.parent / "src" / "backstop_mcp"

_LOG_METHODS = frozenset({"debug", "info", "warning", "error", "exception", "critical", "log"})
_EVENT_FUNCTIONS = frozenset(
    {
        "info_event",
        "warning_event",
        "error_event",
        "failure_event",
        "operation",
        "annotate_tool_call",
    }
)
_SPAN_METHODS = frozenset({"set_attribute", "set_attributes", "add_event"})
_FORBIDDEN = frozenset(
    {
        "arguments",
        "params",
        "json",
        "body",
        "payload",
        "content",
        "text",
        "result",
        "response",
        "document",
        "detail",
        "errors",
        "data",
        "raw",
    }
)
_DUMP_METHODS = frozenset({"model_dump", "json", "getvalue"})

# (path relative to src/backstop_mcp, event name). Each comment names the PR 2 step that
# removes the call.
_KNOWN_VIOLATIONS: frozenset[tuple[str, str]] = frozenset(
    {
        # Phase 6b: str(exc) becomes warning_event(..., exc=exc).
        (
            "features/elicitation_utils/elicit_entity_deletion.py",
            "elicitation.entity_deletion.degraded",
        ),
        ("features/resolution.py", "resolution.elicit.degraded"),
        ("features/resolution.py", "resolution.elicit.capability_check_failed"),
        ("features/auth/provider.py", "auth.login.backstop_unreachable"),
        # Phase 6b: `detail` is Backstop error text.
        (
            "features/activity_history/queries/get_activity_history_query.py",
            "activity_history.stream.forbidden",
        ),
        # Phase 6b: bool(result.body) still names `body`; `is not None` does not.
        (
            "features/activity_history/tools/get_activity_detail.py",
            "activity_history.detail.get.completed",
        ),
        # Phase 6b: isinstance(result, ...) moves out of the log call. `result` is the variable.
        (
            "features/elicitation_utils/elicit_entity_deletion.py",
            "elicitation.entity_deletion.dismissed",
        ),
        ("features/resolution.py", "resolution.elicit.dismissed"),
    }
)


def _sources() -> list[pathlib.Path]:
    return sorted(_SRC.rglob("*.py"))


def _is_logger_call(func: ast.Attribute) -> bool:
    if func.attr not in _LOG_METHODS:
        return False
    target = func.value
    if isinstance(target, ast.Name):
        return target.id == "logger" or target.id.endswith("_logger")
    if isinstance(target, ast.Attribute):
        return target.attr == "logger" or target.attr.endswith("_logger")
    return False


def _is_logged_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Attribute):
        if _is_logger_call(func):
            return True
        return func.attr in _SPAN_METHODS
    if isinstance(func, ast.Name):
        return func.id in _EVENT_FUNCTIONS
    return False


def _event_name(call: ast.Call) -> str:
    for arg in call.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
    return "<dynamic>"


def _is_len(node: ast.Call) -> bool:
    return isinstance(node.func, ast.Name) and node.func.id == "len"


def _is_none_compare(node: ast.Compare) -> bool:
    if len(node.ops) != 1 or not isinstance(node.ops[0], ast.Is | ast.IsNot):
        return False
    comparator = node.comparators[0]
    return isinstance(comparator, ast.Constant) and comparator.value is None


def _is_concealment_call(node: ast.Call) -> bool:
    """`str(exc)` / `repr(...)` of a name, or a method that dumps a whole object."""
    func = node.func
    if isinstance(func, ast.Name) and func.id in {"str", "repr"}:
        return any(isinstance(arg, ast.Name | ast.Attribute) for arg in node.args)
    return isinstance(func, ast.Attribute) and func.attr in _DUMP_METHODS


def _comprehension_offends(generator: ast.comprehension) -> bool:
    """The target name is bound, not logged. The iterable and the filters are."""
    if _offends(generator.iter):
        return True
    return any(_offends(test) for test in generator.ifs)


def _offends(node: ast.AST) -> bool:
    """Whether this expression logs a forbidden value.

    Only the last segment counts: `document.data.id` ends in `id`, so the `data` receiver is
    not a payload. `len(...)` and `is None` hide whatever they wrap. Other calls are entered,
    so `detail=exc.detail` inside `_log_extra(...)` is still visible.
    """
    if isinstance(node, ast.Call) and _is_len(node):
        return False
    if isinstance(node, ast.Compare) and _is_none_compare(node):
        return False
    if isinstance(node, ast.Name):
        return isinstance(node.ctx, ast.Load) and node.id in _FORBIDDEN
    if isinstance(node, ast.Attribute):
        return node.attr in _FORBIDDEN
    if isinstance(node, ast.Call):
        if _is_concealment_call(node):
            return True
        arguments = [*node.args, *(keyword.value for keyword in node.keywords)]
        return any(_offends(argument) for argument in arguments)
    if isinstance(node, ast.ListComp | ast.SetComp | ast.GeneratorExp):
        generators = node.generators
        return _offends(node.elt) or any(_comprehension_offends(item) for item in generators)
    if isinstance(node, ast.DictComp):
        generators = node.generators
        return (
            _offends(node.key)
            or _offends(node.value)
            or any(_comprehension_offends(item) for item in generators)
        )
    return any(_offends(child) for child in ast.iter_child_nodes(node))


def _violations() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for source in _sources():
        tree = ast.parse(source.read_text(), filename=str(source))
        relative = source.relative_to(_SRC).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_logged_call(node):
                continue
            arguments: list[ast.AST] = [*node.args, *(keyword.value for keyword in node.keywords)]
            if any(_offends(argument) for argument in arguments):
                found.add((relative, _event_name(node)))
    return found


class TestNoPayloadLogging:
    def test_only_known_payload_violations_remain(self) -> None:
        unexpected = _violations() - _KNOWN_VIOLATIONS

        assert not unexpected, "new payload logging:\n  " + "\n  ".join(
            f"{path} {event}" for path, event in sorted(unexpected)
        )

    def test_allowlist_entries_still_match_a_real_call(self) -> None:
        stale = _KNOWN_VIOLATIONS - _violations()

        assert not stale, "allowlist entry no longer matches a call:\n  " + "\n  ".join(
            f"{path} {event}" for path, event in sorted(stale)
        )
