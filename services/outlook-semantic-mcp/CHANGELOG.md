# Changelog

## [0.2.9](https://github.com/Unique-AG/connectors/compare/outlook-semantic-mcp@0.2.8...outlook-semantic-mcp@0.2.9) (2026-03-12)


### Bug Fixes

* **outlook-semantic-mcp:** address bugbot comment regarding parameter labels ([#351](https://github.com/Unique-AG/connectors/issues/351)) ([e7e91ca](https://github.com/Unique-AG/connectors/commit/e7e91ca1523fd008935d2a7dd3ced941d2f22cf1))

## [0.2.8](https://github.com/Unique-AG/connectors/compare/outlook-semantic-mcp@0.2.7...outlook-semantic-mcp@0.2.8) (2026-03-12)


### Features

* **outlook-semantic-mcp,unique-api,deps,mcp-server-module,aes-gcm-encryption:** add support for inbox filtering, add inbox sync progress ([#343](https://github.com/Unique-AG/connectors/issues/343)) ([0591a3a](https://github.com/Unique-AG/connectors/commit/0591a3a7ec7afff5847964482eb132d7c94d57b1))


### Bug Fixes

* **outlook-semantic-mcp:** fix equals operator, describe search fields better for the llm ([#349](https://github.com/Unique-AG/connectors/issues/349)) ([29702ce](https://github.com/Unique-AG/connectors/commit/29702ce5a485ecb8d09c2c2d8ea45cb87f4f24e6))

## [0.2.7](https://github.com/Unique-AG/connectors/compare/outlook-semantic-mcp@0.2.6...outlook-semantic-mcp@0.2.7) (2026-03-06)


### Features

* **confluence-connector,unique-api,utils,deps:** implement ingestion pipeline ([#305](https://github.com/Unique-AG/connectors/issues/305)) ([7d2c64c](https://github.com/Unique-AG/connectors/commit/7d2c64c1f4248e06a822a7d827715c4ae001eeec))

## [0.2.6](https://github.com/Unique-AG/connectors/compare/outlook-semantic-mcp@0.2.5...outlook-semantic-mcp@0.2.6) (2026-03-06)


### Bug Fixes

* **outlook-semantic-mcp:** Cleanup logging, add email to logs using smeared ([#331](https://github.com/Unique-AG/connectors/issues/331)) ([6ce957d](https://github.com/Unique-AG/connectors/commit/6ce957dd83b0611445efdf44d3529d7f7afacdf8))

## [0.2.5](https://github.com/Unique-AG/connectors/compare/outlook-semantic-mcp@0.2.4...outlook-semantic-mcp@0.2.5) (2026-03-05)


### Bug Fixes

* **outlook-semantic-mcp,unique-api:** update headers passing and root scope creation ([#329](https://github.com/Unique-AG/connectors/issues/329)) ([00bdb1a](https://github.com/Unique-AG/connectors/commit/00bdb1a7c855b6f6e219528ce3ef0c5d4ab09e1f))

## [0.2.4](https://github.com/Unique-AG/connectors/compare/outlook-semantic-mcp@0.2.3...outlook-semantic-mcp@0.2.4) (2026-03-04)


### Bug Fixes

* **outlook-semantic-mcp:** remove buffered logs ([#326](https://github.com/Unique-AG/connectors/issues/326)) ([596ca58](https://github.com/Unique-AG/connectors/commit/596ca581e14506e4f8fcf6df18eb089ca2a164c3))

## [0.2.3](https://github.com/Unique-AG/connectors/compare/outlook-semantic-mcp@0.2.2...outlook-semantic-mcp@0.2.3) (2026-03-04)


### Bug Fixes

* **outlook-semantic-mcp:** Fix directory structure naming ([#322](https://github.com/Unique-AG/connectors/issues/322)) ([ca5a92d](https://github.com/Unique-AG/connectors/commit/ca5a92da75b104a7058b4fc305452d0f0b929b78))
* **outlook-semantic-mcp:** remove network policy since monorepo will configure it ([#325](https://github.com/Unique-AG/connectors/issues/325)) ([0b1148b](https://github.com/Unique-AG/connectors/commit/0b1148b0cdd1ea9e69281cb72ce1c4f2610f78ad))

## [0.2.2](https://github.com/Unique-AG/connectors/compare/outlook-semantic-mcp@0.2.1...outlook-semantic-mcp@0.2.2) (2026-03-03)


### Bug Fixes

* **outlook-semantic-mcp:** fix env vars in charts ([#319](https://github.com/Unique-AG/connectors/issues/319)) ([1a60d91](https://github.com/Unique-AG/connectors/commit/1a60d91a50f5d72efad1fe52a4e6bfd5b70c9700))

## [0.2.1](https://github.com/Unique-AG/connectors/compare/outlook-semantic-mcp@0.2.0...outlook-semantic-mcp@0.2.1) (2026-03-03)


### Bug Fixes

* **deps:** Declare all dependencies for docker build ([#317](https://github.com/Unique-AG/connectors/issues/317)) ([daa0f45](https://github.com/Unique-AG/connectors/commit/daa0f45efe26e6fd8335af88ecd8094556a1e100))

## [0.2.0](https://github.com/Unique-AG/connectors/compare/outlook-semantic-mcp@0.1.0...outlook-semantic-mcp@0.2.0) (2026-03-02)


### ⚠ BREAKING CHANGES

* **sharepoint-connector,outlook-mcp,factset-mcp:** all git tags no longer include the version 'v'. In a future version, all releases will also not include the v anymore.

### Features

* **outlook-semantic-mcp,ci,main:** UN-16559 set up outlook mcp deployment infrastructure ([#310](https://github.com/Unique-AG/connectors/issues/310)) ([8ea02e1](https://github.com/Unique-AG/connectors/commit/8ea02e1051a02f8826e84bc818d16aebb5d5490b))
* **outlook-semantic-mcp,unique-api,utils:** Implement MCP tools for email search, folder management, and draft creation ([#299](https://github.com/Unique-AG/connectors/issues/299)) ([c84ce92](https://github.com/Unique-AG/connectors/commit/c84ce92cdeb7a62c222ea05bab4deddd5d970081))
* **outlook-semantic-mcp,unique-api:** Fix mail ingestion, handle unknown parent directory, fix lifecycle notification ([#289](https://github.com/Unique-AG/connectors/issues/289)) ([9475591](https://github.com/Unique-AG/connectors/commit/9475591bff0d988cd2076227d5bac012b3f294ad))
* **outlook-semantic-mcp:** base setup for MCP server and outlook email monitoring ([#261](https://github.com/Unique-AG/connectors/issues/261)) ([18e1305](https://github.com/Unique-AG/connectors/commit/18e1305ec93af40d9dd19036203a508f75c768d9))
* **sharepoint-connector,outlook-mcp,factset-mcp:** remove v in tags ([#168](https://github.com/Unique-AG/connectors/issues/168)) ([2f56700](https://github.com/Unique-AG/connectors/commit/2f5670000c968d8bf0e0051eeb47766f586c84cc))
* **unique-api,utils,outlook-semantic-mcp,main:** implement initial mail ingestion and shared libraries ([#286](https://github.com/Unique-AG/connectors/issues/286)) ([b287021](https://github.com/Unique-AG/connectors/commit/b287021246c7f184a1c974734f949f2b7a08e54d))

## Changelog
