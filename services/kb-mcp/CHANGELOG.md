# Changelog

## [0.1.5](https://github.com/Unique-AG/connectors/compare/kb-mcp@0.1.4...kb-mcp@0.1.5) (2026-09-18)


### Features

* **kb-mcp:** allow UniqueQL metadata filters and read_file token overrides ([#1014](https://github.com/Unique-AG/connectors/issues/1014)) ([4788898](https://github.com/Unique-AG/connectors/commit/4788898044f443cf7c9bfbc91c6a39b44b7b17e5))


### Bug Fixes

* **backstop-mcp,hello-mcp,kb-mcp,office-365-mcp:** align the Python image build layouts ([#1038](https://github.com/Unique-AG/connectors/issues/1038)) ([ecdffb6](https://github.com/Unique-AG/connectors/commit/ecdffb656c2f9ed98217c2f4215b33bb9751efd9))


### Dependencies

* **backstop-mcp,hello-mcp,kb-mcp,office-365-mcp:** remove pip from the Python images ([#1033](https://github.com/Unique-AG/connectors/issues/1033)) ([3c0c51f](https://github.com/Unique-AG/connectors/commit/3c0c51f0feb886f41fcc7c6728cea9c040e30741))
* bump basedpyright in /packages/mcp-credential-auth ([#1026](https://github.com/Unique-AG/connectors/issues/1026)) ([61f0ddd](https://github.com/Unique-AG/connectors/commit/61f0dddee8a171e7d8f0398c5f23ada73f7a8b2f))
* bump mcp in /services/backstop-mcp ([#1024](https://github.com/Unique-AG/connectors/issues/1024)) ([f0f626f](https://github.com/Unique-AG/connectors/commit/f0f626fda57d873a783d7eac16e67e23f3393c02))
* bump pydantic-settings in /services/kb-mcp ([#999](https://github.com/Unique-AG/connectors/issues/999)) ([265bacf](https://github.com/Unique-AG/connectors/commit/265bacfb93ccfeda2c0ff6da71cf47457a5deafd))
* bump ruff in /packages/mcp-credential-auth ([#1028](https://github.com/Unique-AG/connectors/issues/1028)) ([bb44f5a](https://github.com/Unique-AG/connectors/commit/bb44f5a5fce11f7022bb67d12f647a25336dddb4))
* bump starlette in /services/backstop-mcp ([#1007](https://github.com/Unique-AG/connectors/issues/1007)) ([5f680b5](https://github.com/Unique-AG/connectors/commit/5f680b52b18891b35875a04d37acd0ad2e5ab49b))
* **hello-mcp,kb-mcp,office-365-mcp:** apply Debian security updates in the Python runtime images ([#1022](https://github.com/Unique-AG/connectors/issues/1022)) ([83a61f8](https://github.com/Unique-AG/connectors/commit/83a61f88d73645a607300ac9dc7ae424a5b29294))
* pin lxml to 6.1.3, bump kiota ([#1050](https://github.com/Unique-AG/connectors/issues/1050)) ([122c820](https://github.com/Unique-AG/connectors/commit/122c820f8a4a0e150318d4c58c587bd4cd0b8919))

## [0.1.4](https://github.com/Unique-AG/connectors/compare/kb-mcp@0.1.3...kb-mcp@0.1.4) (2026-09-11)


### Features

* **kb-mcp:** send service id header ([#1011](https://github.com/Unique-AG/connectors/issues/1011)) ([0bc89c3](https://github.com/Unique-AG/connectors/commit/0bc89c35ed2826c27e19171d45d77da5ff8d1d18))


### Bug Fixes

* **backstop-mcp,confluence-connector,hello-mcp,kb-mcp,office-365-mcp,outlook-semantic-mcp,sharepoint-connector,teams-mcp:** bump base chart dependency to 0.1.0-87990c ([#915](https://github.com/Unique-AG/connectors/issues/915)) ([1bc27a7](https://github.com/Unique-AG/connectors/commit/1bc27a713ab7e2a5bf36671fa1f1f294497c649e))


### Dependencies

* bump pydantic in /services/kb-mcp ([#954](https://github.com/Unique-AG/connectors/issues/954)) ([f7ea6fd](https://github.com/Unique-AG/connectors/commit/f7ea6fde3fb8d5c7e33df42494f8c369a238336a))
* bump ruff from 0.16.4 to 0.16.5 in /services/kb-mcp ([#932](https://github.com/Unique-AG/connectors/issues/932)) ([45650b0](https://github.com/Unique-AG/connectors/commit/45650b0b1692c7603b26f5425918a2cd3e7a959b))
* bump ruff in /services/backstop-mcp ([#953](https://github.com/Unique-AG/connectors/issues/953)) ([3222aa2](https://github.com/Unique-AG/connectors/commit/3222aa2cf86c70f960674f48771f610d13eaf425))
* **kb-mcp:** bump python-dotenv to 1.2.3 ([#977](https://github.com/Unique-AG/connectors/issues/977)) ([f316877](https://github.com/Unique-AG/connectors/commit/f316877bb66ffedfa2a2188ba5b8dafe487308fc))
* put every dependency in the right group, name what was missing, and hold shared versions in the pnpm catalog ([#958](https://github.com/Unique-AG/connectors/issues/958)) ([794092f](https://github.com/Unique-AG/connectors/commit/794092faa348052eddf2be580ed61fc771684b6f))
* upgrade backstop-mcp and kb-mcp to fastmcp 4.0.3 ([#971](https://github.com/Unique-AG/connectors/issues/971)) ([569f04c](https://github.com/Unique-AG/connectors/commit/569f04c1a6c3a1b046e36c5c70fb5319949c139b))
* upgrade uv to 0.12.10 in the Python images ([#975](https://github.com/Unique-AG/connectors/issues/975)) ([8fe0852](https://github.com/Unique-AG/connectors/commit/8fe08523405ddcacfd3fd616758bb8a306855079))

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
