# Changelog

## [0.2.0](https://github.com/Unique-AG/connectors/compare/office-365-mcp@0.1.0...office-365-mcp@0.2.0) (2026-09-09)


### ⚠ BREAKING CHANGES

* **office-365-mcp:** add an Outlook mail surface of 14 tools, and prefix every Teams tool ([#868](https://github.com/Unique-AG/connectors/issues/868))

### Features

* **office-365-mcp:** accept ENTRA_TENANT_ID=organizations for multi-tenant registrations ([#909](https://github.com/Unique-AG/connectors/issues/909)) ([5858025](https://github.com/Unique-AG/connectors/commit/5858025ada29a13488ae6387223e8e13aa1fc8be))
* **office-365-mcp:** add an Outlook calendar surface of five tools ([#908](https://github.com/Unique-AG/connectors/issues/908)) ([6317ba7](https://github.com/Unique-AG/connectors/commit/6317ba7ba48960201a5300105a0c124036a75545))
* **office-365-mcp:** add an Outlook mail surface of 14 tools, and prefix every Teams tool ([#868](https://github.com/Unique-AG/connectors/issues/868)) ([4b9dfe9](https://github.com/Unique-AG/connectors/commit/4b9dfe93367bd31bde4e2e5be6b00a641fe20831))


### Bug Fixes

* **backstop-mcp,confluence-connector,hello-mcp,kb-mcp,office-365-mcp,outlook-semantic-mcp,sharepoint-connector,teams-mcp:** bump base chart dependency to 0.1.0-87990c ([#915](https://github.com/Unique-AG/connectors/issues/915)) ([1bc27a7](https://github.com/Unique-AG/connectors/commit/1bc27a713ab7e2a5bf36671fa1f1f294497c649e))
* **office-365-mcp:** confirm outlook_send_draft on both MCP protocol eras under fastmcp 4 ([#972](https://github.com/Unique-AG/connectors/issues/972)) ([6d8baa5](https://github.com/Unique-AG/connectors/commit/6d8baa5901e959c93f7ae8748ab8db388bbeb3af))
* **office-365-mcp:** raise the pod memory request and limit above the observed working set ([#869](https://github.com/Unique-AG/connectors/issues/869)) ([ff0812a](https://github.com/Unique-AG/connectors/commit/ff0812a66e15c2b97e76411226a906318a882773))


### Dependencies

* **backstop-mcp,hello-mcp,kb-mcp,office-365-mcp:** run the Python services on 3.14 ([#866](https://github.com/Unique-AG/connectors/issues/866)) ([7f2321a](https://github.com/Unique-AG/connectors/commit/7f2321afffb27bcd13e566eea12b0f4c6ceaecc1))
* **backstop-mcp,hello-mcp,kb-mcp,office-365-mcp:** update Python dependencies ([#864](https://github.com/Unique-AG/connectors/issues/864)) ([2833248](https://github.com/Unique-AG/connectors/commit/2833248838b4f6221ccf46f721146e5b1a17c0e4))
* bump msgraph-sdk in /services/office-365-mcp ([#956](https://github.com/Unique-AG/connectors/issues/956)) ([936dee6](https://github.com/Unique-AG/connectors/commit/936dee6749f73d7639c85bf383718e87acc8f1cb))
* bump pydantic in /services/kb-mcp ([#954](https://github.com/Unique-AG/connectors/issues/954)) ([f7ea6fd](https://github.com/Unique-AG/connectors/commit/f7ea6fde3fb8d5c7e33df42494f8c369a238336a))
* bump ruff from 0.16.4 to 0.16.5 in /services/office-365-mcp ([#933](https://github.com/Unique-AG/connectors/issues/933)) ([08be046](https://github.com/Unique-AG/connectors/commit/08be046bc6008e03d32f946b768374763a6c530c))
* bump ruff in /services/backstop-mcp ([#953](https://github.com/Unique-AG/connectors/issues/953)) ([3222aa2](https://github.com/Unique-AG/connectors/commit/3222aa2cf86c70f960674f48771f610d13eaf425))
* bump unique-toolkit[monitoring,otel] in /services/office-365-mcp ([#955](https://github.com/Unique-AG/connectors/issues/955)) ([707c7b5](https://github.com/Unique-AG/connectors/commit/707c7b517b70d86694e93ddd582238a1c10e1102))
* **office-365-mcp:** build and run on one interpreter ([#902](https://github.com/Unique-AG/connectors/issues/902)) ([b4088b1](https://github.com/Unique-AG/connectors/commit/b4088b11e43e4accb0cf40f4cb02e09d29e42f2d))
* **office-365-mcp:** move to fastmcp 4.0.2 ([#914](https://github.com/Unique-AG/connectors/issues/914)) ([c328bcc](https://github.com/Unique-AG/connectors/commit/c328bcce43e90b61cbf8bfb856057ed776933947))
* put every dependency in the right group, name what was missing, and hold shared versions in the pnpm catalog ([#958](https://github.com/Unique-AG/connectors/issues/958)) ([794092f](https://github.com/Unique-AG/connectors/commit/794092faa348052eddf2be580ed61fc771684b6f))
* upgrade uv to 0.12.10 in the Python images ([#975](https://github.com/Unique-AG/connectors/issues/975)) ([8fe0852](https://github.com/Unique-AG/connectors/commit/8fe08523405ddcacfd3fd616758bb8a306855079))

## 0.1.0 (2026-08-27)


### Features

* **office-365-mcp,ci:** add Entra application module with tool-composed Graph permissions ([#848](https://github.com/Unique-AG/connectors/issues/848)) ([f8241c7](https://github.com/Unique-AG/connectors/commit/f8241c7aeb456d9cec2e5c81b154ee9bc603097d))


### Bug Fixes

* **office-365-mcp:** align mcpConfig schema with sibling chart conventions ([#853](https://github.com/Unique-AG/connectors/issues/853)) ([16eb947](https://github.com/Unique-AG/connectors/commit/16eb947740ad72a68ea61d77714b80990fc7c785))


### Miscellaneous Chores

* **office-365-mcp:** name the service Office 365 in its description ([#839](https://github.com/Unique-AG/connectors/issues/839)) ([087c024](https://github.com/Unique-AG/connectors/commit/087c024800b7ab42cc3cc1be65227a9aa7b9ef60))
