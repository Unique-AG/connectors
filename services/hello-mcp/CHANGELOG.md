# Changelog

## [0.1.1](https://github.com/Unique-AG/connectors/compare/hello-mcp@0.1.0...hello-mcp@0.1.1) (2026-09-04)


### Bug Fixes

* **backstop-mcp,confluence-connector,hello-mcp,kb-mcp,office-365-mcp,outlook-semantic-mcp,sharepoint-connector,teams-mcp:** bump base chart dependency to 0.1.0-87990c ([#915](https://github.com/Unique-AG/connectors/issues/915)) ([1bc27a7](https://github.com/Unique-AG/connectors/commit/1bc27a713ab7e2a5bf36671fa1f1f294497c649e))
* **ci,main,hello-mcp,kb-mcp:** keep uv.lock's version in step with pyproject on release ([#856](https://github.com/Unique-AG/connectors/issues/856)) ([12c8512](https://github.com/Unique-AG/connectors/commit/12c851201e87962dff51072d14f70e7570ae99a2))
* **hello-mcp:** run the image as uid 1000, matching the chart ([#737](https://github.com/Unique-AG/connectors/issues/737)) ([ff7c5ac](https://github.com/Unique-AG/connectors/commit/ff7c5ace963d997b2ef32c9614f2ade7f432ff26))


### Dependencies

* **backstop-mcp,hello-mcp,kb-mcp,office-365-mcp:** run the Python services on 3.14 ([#866](https://github.com/Unique-AG/connectors/issues/866)) ([7f2321a](https://github.com/Unique-AG/connectors/commit/7f2321afffb27bcd13e566eea12b0f4c6ceaecc1))
* **backstop-mcp,hello-mcp,kb-mcp,office-365-mcp:** update Python dependencies ([#864](https://github.com/Unique-AG/connectors/issues/864)) ([2833248](https://github.com/Unique-AG/connectors/commit/2833248838b4f6221ccf46f721146e5b1a17c0e4))
* **deps:** bump the service-base-images group across 8 directories with 3 updates ([#788](https://github.com/Unique-AG/connectors/issues/788)) ([7187ed7](https://github.com/Unique-AG/connectors/commit/7187ed758f2a1d4114a01e8dd2e414936ea3b5e4))
* **hello-mcp:** build and run on one interpreter ([#900](https://github.com/Unique-AG/connectors/issues/900)) ([5c9557a](https://github.com/Unique-AG/connectors/commit/5c9557a6f70fa1b4873cc4508b01eae8b8e7871a))

## [0.1.0](https://github.com/Unique-AG/connectors/compare/hello-mcp@0.0.1...hello-mcp@0.1.0) (2026-07-30)


### ⚠ BREAKING CHANGES

* **sharepoint-connector,outlook-mcp,factset-mcp:** all git tags no longer include the version 'v'. In a future version, all releases will also not include the v anymore.

### Features

* **hello-mcp,ci,scripts,main:** add Python hello-mcp FastMCP under services/ ([#712](https://github.com/Unique-AG/connectors/issues/712)) ([ebb889f](https://github.com/Unique-AG/connectors/commit/ebb889fef1887aff12bb6714fc2a6d47a4410b3a))
* **sharepoint-connector,outlook-mcp,factset-mcp:** remove v in tags ([#168](https://github.com/Unique-AG/connectors/issues/168)) ([2f56700](https://github.com/Unique-AG/connectors/commit/2f5670000c968d8bf0e0051eeb47766f586c84cc))
