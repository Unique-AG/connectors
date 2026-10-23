# Why some checks are our own code

Most rules in [`ARCHITECTURE.md`](ARCHITECTURE.md) are configuration for ruff, basedpyright and
import-linter. A few are code of our own, because no tool in the Python stack checks them. This
file names them, the tools we looked at instead, and why we keep the code.

## What is our own code

| Check | Rule it enforces | Why a tool does not do it |
|---|---|---|
| `FeaturePrivacyContract` | One feature imports another only through that feature's top level | import-linter's `protected` contract lets an allowed importer's descendants in too |
| `files_changing_their_type_check` | No file changes its own type check | basedpyright honours a file-level `# pyright: basic` whatever the shared config says |
| `files_turning_rules_off` | No file turns a lint rule off beyond one line | ruff honours `# ruff: noqa: <rule>` and `# ruff: disable[<rule>]` whatever the shared config says |
| `undescribed_tools` | Every tool and parameter has a description | MCP-specific: needs the schema the server lists |
| `tools_with_a_root_combinator` | No `anyOf`, `oneOf`, `allOf` or `not` at a tool schema's root | MCP-specific: needs the schema the server lists |
| `masks_error_details` | An unexpected error reaches the client without its message | Needs to call a tool that raises on the built server |
| `settings_showing_input_in_errors` | A settings error does not print its input | Needs every loaded settings class |
| `tool_surface` | What a client sees matches a snapshot | MCP-specific: needs the tools the server lists |
| `mcp_architecture.check` | The checks from `files_changing_their_type_check` on run | A pytest run lets a `conftest.py` skip or rewrite a check's outcome |

## Alternatives we looked at

### Tach instead of, or beside, import-linter

[Tach](https://github.com/tach-org/tach) checks imports against modules declared in `tach.toml`.
Its `interfaces` express feature privacy without code, which import-linter cannot. Against our
import rules:

| Rule | import-linter | Tach |
|---|---|---|
| Layers only import downwards, no module outside them | `layers`, `exhaustive` | `layers`, `root_module = "forbid"` |
| A layer is imported through its top level | `protected` | `interfaces` |
| Feature privacy | `FeaturePrivacyContract` | `interfaces` |
| No cycle between siblings, at any depth | `acyclic_siblings` | `forbid_circular_dependencies`, between declared modules only |
| `contexts`, `persistence` and `shared` import nothing from `fastmcp`, `mcp` or `mcp_types` | `forbidden` | Not supported |
| `shared.contracts` imports nothing from `sqlalchemy`, `httpx2` or `cryptography` | `forbidden` | Not supported |
| Indirect chains (`a → b → c`) | Checked | Direct imports only |
| A contract type of our own | Python plugin | Not supported |

Tach cannot extend a shared file either, so the scaffold would still render its config.

Replacing import-linter loses the `fastmcp` ban, which a nested `ruff.toml` with `TID251` under
`contexts/`, `persistence/` and `shared/` would have to take over. Running both means two configs per MCP,
two CI steps, and rules that disagree when a chain is indirect, all to retire one class of about
70 lines.

### The other checks

| Check | Alternative | Why not |
|---|---|---|
| `files_changing_their_type_check` | basedpyright's `reportIgnoreCommentWithoutRule` | Already on through `all` mode, but it only covers `# pyright: ignore`, not a file-level mode |
| `files_turning_rules_off` | ruff's `PGH004` | Already on, but it only flags a `noqa` that names no rule |
| `masks_error_details`, `settings_showing_input_in_errors` | A Semgrep rule | Matches the source, not the built object, so a server or settings class built indirectly slips past. Adds a tool for two checks |
| `undescribed_tools`, `tools_with_a_root_combinator` | A Semgrep rule on `Field(description=...)` | Cannot see the schema FastMCP generates, nor tools served from an OpenAPI spec |
| `tool_surface` | syrupy or pytest-regressions | Both compare inside pytest, where a `conftest.py` can skip the comparison |

## Why we keep the code

- It is small, tested, and each check fails with the tool or the line at fault.
- `FeaturePrivacyContract` uses import-linter's plugin API and reports with the other contracts,
  in the same CI step.
- One tool per concern keeps one answer per rule.
- Its one fragile point is `importlinter.domain.imports.Module`, an internal path. The `<3`
  pin on import-linter guards it.

## When to look again

- More contract types of our own pile up: then Tach's built-in `interfaces` and `visibility`
  pay for a migration. Replace import-linter rather than run both.
- We want what only Tach has, such as running only the tests a change affects, or the
  dependency graph.
- An import-linter major version breaks `FeaturePrivacyContract` in a way a few lines do not fix.
