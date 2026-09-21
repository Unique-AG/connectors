# Changelog

## [0.1.1](https://github.com/Unique-AG/connectors/compare/hello-mcp@0.1.0...hello-mcp@0.1.1) (2026-09-21)


### Bug Fixes

* **backstop-mcp,confluence-connector,hello-mcp,kb-mcp,office-365-mcp,outlook-semantic-mcp,sharepoint-connector,teams-mcp:** bump base chart dependency to 0.1.0-87990c ([#915](https://github.com/Unique-AG/connectors/issues/915)) ([1bc27a7](https://github.com/Unique-AG/connectors/commit/1bc27a713ab7e2a5bf36671fa1f1f294497c649e))
* **backstop-mcp,hello-mcp,kb-mcp,office-365-mcp:** align the Python image build layouts ([#1038](https://github.com/Unique-AG/connectors/issues/1038)) ([ecdffb6](https://github.com/Unique-AG/connectors/commit/ecdffb656c2f9ed98217c2f4215b33bb9751efd9))
* **ci,main,hello-mcp,kb-mcp:** keep uv.lock's version in step with pyproject on release ([#856](https://github.com/Unique-AG/connectors/issues/856)) ([12c8512](https://github.com/Unique-AG/connectors/commit/12c851201e87962dff51072d14f70e7570ae99a2))
* **hello-mcp:** run the image as uid 1000, matching the chart ([#737](https://github.com/Unique-AG/connectors/issues/737)) ([ff7c5ac](https://github.com/Unique-AG/connectors/commit/ff7c5ace963d997b2ef32c9614f2ade7f432ff26))


### Dependencies

* **backstop-mcp,hello-mcp,kb-mcp,office-365-mcp:** remove pip from the Python images ([#1033](https://github.com/Unique-AG/connectors/issues/1033)) ([3c0c51f](https://github.com/Unique-AG/connectors/commit/3c0c51f0feb886f41fcc7c6728cea9c040e30741))
* **backstop-mcp,hello-mcp,kb-mcp,office-365-mcp:** run the Python services on 3.14 ([#866](https://github.com/Unique-AG/connectors/issues/866)) ([7f2321a](https://github.com/Unique-AG/connectors/commit/7f2321afffb27bcd13e566eea12b0f4c6ceaecc1))
* **backstop-mcp,hello-mcp,kb-mcp,office-365-mcp:** update Python dependencies ([#864](https://github.com/Unique-AG/connectors/issues/864)) ([2833248](https://github.com/Unique-AG/connectors/commit/2833248838b4f6221ccf46f721146e5b1a17c0e4))
* bump basedpyright in /packages/mcp-credential-auth ([#1026](https://github.com/Unique-AG/connectors/issues/1026)) ([61f0ddd](https://github.com/Unique-AG/connectors/commit/61f0dddee8a171e7d8f0398c5f23ada73f7a8b2f))
* bump fastmcp from 3.4.7 to 4.0.0 in /services/hello-mcp in the major group across 1 directory ([#927](https://github.com/Unique-AG/connectors/issues/927)) ([2c19afa](https://github.com/Unique-AG/connectors/commit/2c19afaf97d3b87b814820f997e1d9bfa81c0b2a))
* bump fastmcp in /services/hello-mcp ([#947](https://github.com/Unique-AG/connectors/issues/947)) ([0e954b2](https://github.com/Unique-AG/connectors/commit/0e954b2ec5e3f392760b16292f98193d3d139d70))
* bump fastmcp in /services/hello-mcp ([#998](https://github.com/Unique-AG/connectors/issues/998)) ([adf016d](https://github.com/Unique-AG/connectors/commit/adf016d18b7c5b323e444d110000a6d300cc914a))
* bump pydantic in /services/kb-mcp ([#954](https://github.com/Unique-AG/connectors/issues/954)) ([f7ea6fd](https://github.com/Unique-AG/connectors/commit/f7ea6fde3fb8d5c7e33df42494f8c369a238336a))
* bump pydantic-settings in /services/kb-mcp ([#999](https://github.com/Unique-AG/connectors/issues/999)) ([265bacf](https://github.com/Unique-AG/connectors/commit/265bacfb93ccfeda2c0ff6da71cf47457a5deafd))
* bump ruff from 0.16.4 to 0.16.5 in /services/hello-mcp ([#931](https://github.com/Unique-AG/connectors/issues/931)) ([df9fd1e](https://github.com/Unique-AG/connectors/commit/df9fd1e781d724afdc23c5742d46c501fb94d676))
* bump ruff in /packages/mcp-credential-auth ([#1028](https://github.com/Unique-AG/connectors/issues/1028)) ([bb44f5a](https://github.com/Unique-AG/connectors/commit/bb44f5a5fce11f7022bb67d12f647a25336dddb4))
* bump ruff in /services/backstop-mcp ([#953](https://github.com/Unique-AG/connectors/issues/953)) ([3222aa2](https://github.com/Unique-AG/connectors/commit/3222aa2cf86c70f960674f48771f610d13eaf425))
* bump starlette in /services/backstop-mcp ([#1007](https://github.com/Unique-AG/connectors/issues/1007)) ([5f680b5](https://github.com/Unique-AG/connectors/commit/5f680b52b18891b35875a04d37acd0ad2e5ab49b))
* **deps:** bump the service-base-images group across 8 directories with 3 updates ([#788](https://github.com/Unique-AG/connectors/issues/788)) ([7187ed7](https://github.com/Unique-AG/connectors/commit/7187ed758f2a1d4114a01e8dd2e414936ea3b5e4))
* **hello-mcp,kb-mcp,office-365-mcp:** apply Debian security updates in the Python runtime images ([#1022](https://github.com/Unique-AG/connectors/issues/1022)) ([83a61f8](https://github.com/Unique-AG/connectors/commit/83a61f88d73645a607300ac9dc7ae424a5b29294))
* **hello-mcp:** build and run on one interpreter ([#900](https://github.com/Unique-AG/connectors/issues/900)) ([5c9557a](https://github.com/Unique-AG/connectors/commit/5c9557a6f70fa1b4873cc4508b01eae8b8e7871a))
* put every dependency in the right group, name what was missing, and hold shared versions in the pnpm catalog ([#958](https://github.com/Unique-AG/connectors/issues/958)) ([794092f](https://github.com/Unique-AG/connectors/commit/794092faa348052eddf2be580ed61fc771684b6f))
* upgrade uv to 0.12.10 in the Python images ([#975](https://github.com/Unique-AG/connectors/issues/975)) ([8fe0852](https://github.com/Unique-AG/connectors/commit/8fe08523405ddcacfd3fd616758bb8a306855079))

## [0.1.0](https://github.com/Unique-AG/connectors/compare/hello-mcp@0.0.1...hello-mcp@0.1.0) (2026-07-30)


### ⚠ BREAKING CHANGES

* **sharepoint-connector,outlook-mcp,factset-mcp:** all git tags no longer include the version 'v'. In a future version, all releases will also not include the v anymore.

### Features

* **hello-mcp,ci,scripts,main:** add Python hello-mcp FastMCP under services/ ([#712](https://github.com/Unique-AG/connectors/issues/712)) ([ebb889f](https://github.com/Unique-AG/connectors/commit/ebb889fef1887aff12bb6714fc2a6d47a4410b3a))
* **sharepoint-connector,outlook-mcp,factset-mcp:** remove v in tags ([#168](https://github.com/Unique-AG/connectors/issues/168)) ([2f56700](https://github.com/Unique-AG/connectors/commit/2f5670000c968d8bf0e0051eeb47766f586c84cc))
