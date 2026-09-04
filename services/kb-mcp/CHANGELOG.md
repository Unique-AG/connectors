# Changelog

## [0.1.4](https://github.com/Unique-AG/connectors/compare/kb-mcp@0.1.3...kb-mcp@0.1.4) (2026-09-04)


### Bug Fixes

* **backstop-mcp,confluence-connector,hello-mcp,kb-mcp,office-365-mcp,outlook-semantic-mcp,sharepoint-connector,teams-mcp:** bump base chart dependency to 0.1.0-87990c ([#915](https://github.com/Unique-AG/connectors/issues/915)) ([1bc27a7](https://github.com/Unique-AG/connectors/commit/1bc27a713ab7e2a5bf36671fa1f1f294497c649e))

## [0.1.3](https://github.com/Unique-AG/connectors/compare/kb-mcp@0.1.2...kb-mcp@0.1.3) (2026-09-03)


### Bug Fixes

* **kb-mcp:** bound content-tree resources and authentication ([#895](https://github.com/Unique-AG/connectors/issues/895)) ([8c4550a](https://github.com/Unique-AG/connectors/commit/8c4550a937a0ff51d518108996358556bd85da02))
* **kb-mcp:** resolve read_file's file-type dispatch from mime_type ([#878](https://github.com/Unique-AG/connectors/issues/878)) ([b38623d](https://github.com/Unique-AG/connectors/commit/b38623dfc2b1b50db6196e45219c2a8cba1f3ee1))

## [0.1.2](https://github.com/Unique-AG/connectors/compare/kb-mcp@0.1.1...kb-mcp@0.1.2) (2026-08-31)


### Features

* **kb-mcp:** add a KB_MCP_ENABLED_TOOLS allowlist to ship search-only ([#872](https://github.com/Unique-AG/connectors/issues/872)) ([6289cdb](https://github.com/Unique-AG/connectors/commit/6289cdbf802337845a01b890ace9f20ec7acfbe7))


### Bug Fixes

* **ci,main,hello-mcp,kb-mcp:** keep uv.lock's version in step with pyproject on release ([#856](https://github.com/Unique-AG/connectors/issues/856)) ([12c8512](https://github.com/Unique-AG/connectors/commit/12c851201e87962dff51072d14f70e7570ae99a2))

## [0.1.1](https://github.com/Unique-AG/connectors/compare/kb-mcp@0.1.0...kb-mcp@0.1.1) (2026-08-14)


### Bug Fixes

* **kb-mcp:** return ToolResult and wire [sourceN] references [UN-24212] ([#781](https://github.com/Unique-AG/connectors/issues/781)) ([573c9bc](https://github.com/Unique-AG/connectors/commit/573c9bcf3ba51114e5077d76c40393be55f7d19b))

## [0.1.0](https://github.com/Unique-AG/connectors/compare/kb-mcp@0.0.1...kb-mcp@0.1.0) (2026-08-11)


### ⚠ BREAKING CHANGES

* **sharepoint-connector,outlook-mcp,factset-mcp:** all git tags no longer include the version 'v'. In a future version, all releases will also not include the v anymore.

### Features

* **kb-mcp,ci,scripts,main:** migrate Knowledge Base Search MCP into connectors as kb-mcp ([#719](https://github.com/Unique-AG/connectors/issues/719)) ([82b79a8](https://github.com/Unique-AG/connectors/commit/82b79a8667c083ea53f03c89d40e9307e6b067ea))
* **sharepoint-connector,outlook-mcp,factset-mcp:** remove v in tags ([#168](https://github.com/Unique-AG/connectors/issues/168)) ([2f56700](https://github.com/Unique-AG/connectors/commit/2f5670000c968d8bf0e0051eeb47766f586c84cc))


### Bug Fixes

* **kb-mcp:** persist OAuth state in Postgres and address PR [#719](https://github.com/Unique-AG/connectors/issues/719) review feedback ([#756](https://github.com/Unique-AG/connectors/issues/756)) ([25e8cdb](https://github.com/Unique-AG/connectors/commit/25e8cdb08aafaeae2e7c3a36de102fc15295a285))
