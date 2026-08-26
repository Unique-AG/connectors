#!/usr/bin/env python3
"""render-terraform-registry.py — render the Entra module's registry locals from the Python.

Usage:
  scripts/render-terraform-registry.py [--check]

  --check  Verify that the committed registry.generated.tf.json matches what would be
           generated. Exits 1 on drift (suitable for CI).

Requirements:
  - the service's own virtualenv, because this imports `office_365_mcp` (`uv run python …`)
"""

import argparse
import difflib
import json
import pathlib
import sys
from collections.abc import Sequence

from office_365_mcp.auth import _CALLBACK_PATH, _REQUIRED_SCOPES
from office_365_mcp.server.manifest import NEEDS_ADMIN_CONSENT
from office_365_mcp.shared.seam import _GRAPH_SCOPE_PREFIX, REQUESTABLE_PERMISSIONS
from office_365_mcp.tools import _TOOL_MODULES, ALWAYS_ON, PRESETS

_INVOCATION = "scripts/render-terraform-registry.py"

TARGET = (
    pathlib.Path(__file__).resolve().parents[1]
    / "deploy"
    / "terraform"
    / "azure"
    / "office-365-mcp-entra-application"
    / "registry.generated.tf.json"
)


def document() -> dict[str, object]:
    """The whole file, as the objects `json.dump` writes it from.

    Native Terraform JSON rather than HCL, so this generator is the tables' only writer and the
    `.generated.` in the filename is the only warning a reader gets — JSON carries no comment.
    """
    return {
        # A list of blocks, which is what the JSON configuration syntax makes of a repeatable
        # block; the module declares no other `locals`, so it is a list of exactly one.
        "locals": [
            {
                # A list rather than a map, in `_TOOL_MODULES` order: a `for` over a map iterates
                # in lexical key order, which would derive a permission order the pod never
                # computes, and `tool_surface.permissions` is diffed against GET /manifest.
                "tool_registry": [
                    {
                        "name": module.TOOL_NAME,
                        "permissions": list(module.GRAPH_PERMISSIONS),
                    }
                    for module in _TOOL_MODULES
                ],
                # A plain list, not a `for` over `local.tool_registry`: a generated file has no
                # reason to carry an expression.
                "tool_names": [module.TOOL_NAME for module in _TOOL_MODULES],
                "always_on": ALWAYS_ON,
                "presets": {name: list(tools) for name, tools in PRESETS.items()},
                "requestable_permissions": _requestable_permissions(),
                "needs_admin_consent": dict(NEEDS_ADMIN_CONSENT),
                "graph_scope_prefix": _GRAPH_SCOPE_PREFIX,
                "api_scope_name": _api_scope_name(),
                "callback_path": _CALLBACK_PATH,
            }
        ]
    }


def render() -> str:
    return json.dumps(document(), indent=2) + "\n"


def _requestable_permissions() -> list[str]:
    """`REQUESTABLE_PERMISSIONS` is a frozenset, so the order is this function's to decide.

    First appearance over the registry, which is the order every other permission list in the
    module is in. A ceiling entry no tool declares yet — which `seam.py` permits — is sorted onto
    the end, so the file stays byte-stable across runs whatever the set's iteration order is.
    """
    declared = dict.fromkeys(
        permission for module in _TOOL_MODULES for permission in module.GRAPH_PERMISSIONS
    )
    ordered = [permission for permission in declared if permission in REQUESTABLE_PERMISSIONS]
    return ordered + sorted(REQUESTABLE_PERMISSIONS.difference(ordered))


def _api_scope_name() -> str:
    """The one scope `AzureProvider` is handed. A registration exposing any other name leaves every
    request failing FastMCP's own scope check with nothing in the module wrong.
    """
    assert len(_REQUIRED_SCOPES) == 1, (
        "the module exposes exactly one `oauth2_permission_scope`, so auth.py declaring "
        + f"{len(_REQUIRED_SCOPES)} required scopes has outgrown this generator: {_REQUIRED_SCOPES}"
    )
    return _REQUIRED_SCOPES[0]


def _check(generated: str) -> int:
    if not TARGET.exists():
        print(f"DRIFT: {TARGET.name} is missing — run {_INVOCATION}.", file=sys.stderr)
        return 1

    committed = TARGET.read_text()
    if committed == generated:
        print(f"  OK: {TARGET.name}")
        return 0

    print(
        f"DRIFT: {TARGET.name} is out of date. Run {_INVOCATION} to regenerate it.",
        file=sys.stderr,
    )
    sys.stderr.writelines(
        difflib.unified_diff(
            committed.splitlines(keepends=True),
            generated.splitlines(keepends=True),
            fromfile=f"{TARGET.name} (committed)",
            tofile=f"{TARGET.name} (generated)",
        )
    )
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=_summary())
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed file matches what would be generated; exit 1 on drift",
    )
    arguments = parser.parse_args(argv)
    generated = render()

    if arguments.check:
        return _check(generated)

    TARGET.write_text(generated)
    print(f"  Written: {TARGET}")
    return 0


def _summary() -> str:
    assert __doc__ is not None, "this module's docstring is the only help text there is"
    return __doc__.splitlines()[0]


if __name__ == "__main__":
    raise SystemExit(main())
