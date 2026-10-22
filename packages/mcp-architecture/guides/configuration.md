# Where each rule is configured

The MCP's `pyproject.toml` holds each tool's table, and the scaffold writes it.

- **ruff.** `uv run mcp-architecture-lint` runs ruff with `mcp-architecture`'s `code_style.toml`
  passed as `--config`, so nothing in the MCP, whether `[tool.ruff]`, a `ruff.toml` or an
  `.ignore`, changes what CI checks. It then runs ruff with the MCP's own configuration, for a
  rule the MCP adds with `extend-select`, and names the rules that configuration hides from the
  editor. `--fix` formats and fixes what ruff can. `[tool.ruff]` is there for the editor and a
  bare `uv run ruff check`: it extends `code_style.toml` and repeats its two `per-file-ignores`,
  which ruff reads from the shared file's folder through `extend`, where they match nothing. A
  `# noqa: <rule>` on the line that needs it, with the reason beside it, is fine, as Google's
  guide allows. A bare `# noqa` breaks the style (`PGH004`). A `# ruff: noqa` or `# ruff: disable`
  comment turns a rule off for the rest of the file, so `mcp-architecture-check` fails on one
  outside generated code.
- **basedpyright.** `[tool.basedpyright]` extends `type_check.json`. It sets `extends`,
  `venvPath`, `venv`, `pythonVersion`, `include = ["src", "tests"]`, `strict`,
  `executionEnvironments` and reports, and nothing else: any other option, such as
  `analyzeUnannotatedFunctions` or `baselineFile`, turns the check down. Make a report stricter
  there, never turn one down. An `executionEnvironments` entry sets only `root`, `extraPaths`,
  `pythonVersion` and reports. The one the scaffold writes lets `tests/` use private names; it
  sits in the MCP's table because basedpyright reads a root in an extended file from that file's
  folder. `uv run mcp-architecture-check` fails on anything else, on a `pyrightconfig.json`,
  which basedpyright reads in place of the table, and on a `.basedpyright/` baseline, whose
  errors basedpyright drops. Never run `basedpyright --writebaseline`.
- **import-linter.** `uv run mcp-architecture-imports` checks the contracts every MCP keeps, as
  `mcp_architecture.render_importlinter` gives them, then the MCP's own in `[tool.importlinter]`.
  Nothing in that table changes the shared ones. Add a contract of the MCP's own there. Never add
  an `ignore_imports` entry or an option such as `exclude_type_checking_imports` to make a change
  pass: move the code to the layer it belongs in.

What ruff cannot check is left to review: import modules rather than names where the guide asks
it, keep functions short, and avoid the guide's power features.
