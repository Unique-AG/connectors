# Where each rule is configured

The MCP's `pyproject.toml` holds each tool's table, and the scaffold writes it. CI runs each tool
once, with that table, as for any other service. A table that loosens a shared rule is an
exception, and review decides whether it stays. An agent never makes that exception itself: it
tries every other fix first, and asks the user when none works.

- **ruff.** `[tool.ruff]` extends `mcp-architecture`'s `code_style.toml`. Add a rule there with
  `extend-select`. A `per-file-ignores` entry goes in this table rather than the shared file,
  since ruff reads a path there from the shared file's folder, where it matches nothing; like any
  other loosening, it is an exception for review. A `# noqa: <rule>` on the line that needs it,
  with the reason beside it, is fine, as Google's guide allows. A bare `# noqa` breaks the style
  (`PGH004`). A `# ruff: noqa` or `# ruff: disable` comment turns a rule off for the rest of the
  file, as a `per-file-ignores` entry would, so it is an exception for review too; only the
  codegen's output in `upstream/generated/` carries one.
- **basedpyright.** `[tool.basedpyright]` extends `type_check.json`. Make a report stricter there,
  never turn one down. The `executionEnvironments` entry the scaffold writes lets `tests/` use
  private names; it sits in the MCP's table because basedpyright reads a root in an extended file
  from that file's folder. Never run `basedpyright --writebaseline`, and never add a file-level
  `# pyright:` comment such as `# pyright: basic`: only `# pyright: ignore[<rule>]` on one line.
- **import-linter.** `[tool.importlinter]` holds the contracts every MCP keeps, as
  `mcp_architecture.render_importlinter` gives them. import-linter cannot extend a shared file,
  so the scaffold writes them in. Add a contract of the MCP's own below them. Never add an
  `ignore_imports` entry or an option such as `exclude_type_checking_imports` to make a change
  pass: move the code to the layer it belongs in.

What ruff cannot check is left to review: import modules rather than names where the guide asks
it, keep functions short, and avoid the guide's power features.
