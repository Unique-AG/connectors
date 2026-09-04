# Changelog

## [0.2.0](https://github.com/Unique-AG/connectors/compare/office-365-mcp@0.1.0...office-365-mcp@0.2.0) (2026-09-04)


### ⚠ BREAKING CHANGES

* **office-365-mcp:** add an Outlook mail surface of 14 tools, and prefix every Teams tool ([#868](https://github.com/Unique-AG/connectors/issues/868))

### Features

* **office-365-mcp:** add an Outlook mail surface of 14 tools, and prefix every Teams tool ([#868](https://github.com/Unique-AG/connectors/issues/868)) ([4b9dfe9](https://github.com/Unique-AG/connectors/commit/4b9dfe93367bd31bde4e2e5be6b00a641fe20831))


### Bug Fixes

* **backstop-mcp,confluence-connector,hello-mcp,kb-mcp,office-365-mcp,outlook-semantic-mcp,sharepoint-connector,teams-mcp:** bump base chart dependency to 0.1.0-87990c ([#915](https://github.com/Unique-AG/connectors/issues/915)) ([1bc27a7](https://github.com/Unique-AG/connectors/commit/1bc27a713ab7e2a5bf36671fa1f1f294497c649e))
* **office-365-mcp:** raise the pod memory request and limit above the observed working set ([#869](https://github.com/Unique-AG/connectors/issues/869)) ([ff0812a](https://github.com/Unique-AG/connectors/commit/ff0812a66e15c2b97e76411226a906318a882773))


### Dependencies

* **backstop-mcp,hello-mcp,kb-mcp,office-365-mcp:** run the Python services on 3.14 ([#866](https://github.com/Unique-AG/connectors/issues/866)) ([7f2321a](https://github.com/Unique-AG/connectors/commit/7f2321afffb27bcd13e566eea12b0f4c6ceaecc1))
* **backstop-mcp,hello-mcp,kb-mcp,office-365-mcp:** update Python dependencies ([#864](https://github.com/Unique-AG/connectors/issues/864)) ([2833248](https://github.com/Unique-AG/connectors/commit/2833248838b4f6221ccf46f721146e5b1a17c0e4))
* **office-365-mcp:** build and run on one interpreter ([#902](https://github.com/Unique-AG/connectors/issues/902)) ([b4088b1](https://github.com/Unique-AG/connectors/commit/b4088b11e43e4accb0cf40f4cb02e09d29e42f2d))

## 0.1.0 (2026-08-27)


### Features

* **office-365-mcp,ci:** add Entra application module with tool-composed Graph permissions ([#848](https://github.com/Unique-AG/connectors/issues/848)) ([f8241c7](https://github.com/Unique-AG/connectors/commit/f8241c7aeb456d9cec2e5c81b154ee9bc603097d))


### Bug Fixes

* **office-365-mcp:** align mcpConfig schema with sibling chart conventions ([#853](https://github.com/Unique-AG/connectors/issues/853)) ([16eb947](https://github.com/Unique-AG/connectors/commit/16eb947740ad72a68ea61d77714b80990fc7c785))


### Miscellaneous Chores

* **office-365-mcp:** name the service Office 365 in its description ([#839](https://github.com/Unique-AG/connectors/issues/839)) ([087c024](https://github.com/Unique-AG/connectors/commit/087c024800b7ab42cc3cc1be65227a9aa7b9ef60))
