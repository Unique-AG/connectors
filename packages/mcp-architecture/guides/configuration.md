# Where each rule is configured

The MCP's `pyproject.toml` holds each tool's configuration, and the scaffold writes it.
`uv run mcp-architecture-check` fails when a table below sets anything else or drops what the
shared files and `render_importlinter` give.

- `[tool.ruff]` extends `mcp-architecture`'s `code_style.toml`, and `uv run ruff check --fix`
  fixes most of what it finds. It sets `extend`, `target-version`, `exclude = [".venv"]` and, under
  `lint`, `extend-select` and `per-file-ignores`, and nothing else: any other key or sub-table,
  such as `[tool.ruff.lint.pylint]`, replaces a setting of the shared style. A `per-file-ignores`
  entry covers `src/<package>/upstream/generated/` only, apart from the one that limits `PLR0917`
  to `contexts/`, which sits in the MCP's table and not in `code_style.toml` because ruff reads a
  path in an extended file from that file's folder. A `# noqa: <rule>` on the line that needs it,
  with the reason beside it, is fine, as Google's guide allows. A bare `# noqa` breaks the style
  (`PGH004`). A `# ruff: noqa` or `# ruff: disable` comment turns a rule off for the rest of the
  file, as a `per-file-ignores` entry would, so `mcp-architecture-check` fails on one outside
  generated code.
- `[tool.basedpyright]` extends `type_check.json`. It sets `extends`, `venvPath`, `venv`,
  `pythonVersion`, `include = ["src", "tests"]`, `strict`, `executionEnvironments` and reports,
  and nothing else: any other option, such as `analyzeUnannotatedFunctions` or `baselineFile`,
  turns the check down. Make a report stricter there, never turn one down. An
  `executionEnvironments` entry sets only `root`, `extraPaths`, `pythonVersion` and reports. The
  one the scaffold writes lets `tests/` use private names, for the same reason as the ruff entry
  above. Never run `basedpyright --writebaseline`: basedpyright drops every error the
  `.basedpyright/` baseline lists.
- `[tool.importlinter]` holds the contracts, which `mcp_architecture.render_importlinter` writes.
  import-linter has no way to extend a shared file, so each MCP carries its own copy, and
  `uv run mcp-architecture-check --update` writes it back when the shared contracts change,
  keeping the MCP's own. Never loosen a contract, add an `ignore_imports` entry or set an option
  such as `exclude_type_checking_imports` to make a change pass. Move the code to the layer it
  belongs in. A contract of your own, stricter than these, is fine to add after them.

The check also fails when a `.basedpyright/` baseline exists, and when a `ruff.toml`,
`.ruff.toml`, nested `pyproject.toml`, `pyrightconfig.json`, `.importlinter` or `setup.cfg` would
be read in place of a table. What ruff cannot check is left to review: import modules rather
than names where the guide asks it, keep functions short, and avoid the guide's power features.
