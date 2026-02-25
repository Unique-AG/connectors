# Changelog

## [0.2.5](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.2.4...teams-mcp@0.2.5) (2026-02-20)


### Features

* **teams-mcp:** add semantic transcript search with reference support ([#254](https://github.com/Unique-AG/connectors/issues/254)) ([d5a05e0](https://github.com/Unique-AG/connectors/commit/d5a05e0d7f6357dae26d900a88eb008868f52bf9))

## [0.2.4](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.2.3...teams-mcp@0.2.4) (2026-02-12)


### Features

* **teams-mcp:** add recording permission and update documentation ([#273](https://github.com/Unique-AG/connectors/issues/273)) ([4dd5f04](https://github.com/Unique-AG/connectors/commit/4dd5f04e3b0e4a059592caba0527d8554196753b))
* **teams-mcp:** add recording storage as accompanying artifact to transcripts ([#267](https://github.com/Unique-AG/connectors/issues/267)) ([e913293](https://github.com/Unique-AG/connectors/commit/e91329372fcc8541824322c03540674c253f1d00))

## [0.2.3](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.2.2...teams-mcp@0.2.3) (2026-01-26)


### Features

* **teams-mcp:** use flat folder structure and fix meeting dates ([#235](https://github.com/Unique-AG/connectors/issues/235)) ([4105c02](https://github.com/Unique-AG/connectors/commit/4105c02c1f881517768e1e552c37621812694dda))

## [0.2.2](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.2.1...teams-mcp@0.2.2) (2026-01-23)


### Bug Fixes

* **teams-mcp:** add debug logging for write URL transformation ([#233](https://github.com/Unique-AG/connectors/issues/233)) ([7442123](https://github.com/Unique-AG/connectors/commit/7442123b7f67197dd86b9a6a81aa5888114333b9))
* **teams-mcp:** include port in storage endpoint logging ([#231](https://github.com/Unique-AG/connectors/issues/231)) ([92a4c6f](https://github.com/Unique-AG/connectors/commit/92a4c6ffdde4dff9a6a9eb4edfd49021da427c90))

## [0.2.1](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.2.0...teams-mcp@0.2.1) (2026-01-22)


### Features

* **teams-mcp:** remove MP4 recording ingestion from transcript processing ([#221](https://github.com/Unique-AG/connectors/issues/221)) ([73f2024](https://github.com/Unique-AG/connectors/commit/73f2024d83ccf8494a05a59ff7e16b704c967b9a))


### Bug Fixes

* **teams-mcp:** improve calendar event matching, scope paths, and metadata handling ([#230](https://github.com/Unique-AG/connectors/issues/230)) ([ef16658](https://github.com/Unique-AG/connectors/commit/ef16658d27d112da37ae973700935e2977e4adce))

## [0.2.0](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.1.1...teams-mcp@0.2.0) (2026-01-21)


### ⚠ BREAKING CHANGES

* **teams-mcp:** Subscriptions are no longer created automatically on authentication. Users must explicitly call start_kb_integration to begin transcript ingestion.

### Features

* **teams-mcp:** add GraphError exception filter ([#211](https://github.com/Unique-AG/connectors/issues/211)) ([ade292c](https://github.com/Unique-AG/connectors/commit/ade292ce2a98440219d397e441d15b9f27f022a1))
* **teams-mcp:** add KB integration MCP tools for explicit subscription management ([2f11dee](https://github.com/Unique-AG/connectors/commit/2f11deea20d29f05eef5bb84beb8ea79a7593f9a))
* **teams-mcp:** detect recurring meetings via calendar events ([#210](https://github.com/Unique-AG/connectors/issues/210)) ([644af78](https://github.com/Unique-AG/connectors/commit/644af785ce48db762adbc1554f8b4194a5c0b7e1))
* **teams-mcp:** merge docs to add auto docs publish workflows ([#202](https://github.com/Unique-AG/connectors/issues/202)) ([13081f0](https://github.com/Unique-AG/connectors/commit/13081f01cf12d510af130672c2ab8eca0137d975))


### Bug Fixes

* **outlook:** Fixes the MCP connector to work with the v1.25.2 sdk ([#213](https://github.com/Unique-AG/connectors/issues/213)) ([52e028b](https://github.com/Unique-AG/connectors/commit/52e028b890f249907331e005ca97e770db5b95d1))

## [0.1.1](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.1.0...teams-mcp@0.1.1) (2026-01-13)


### Features

* **teams-mcp:** auto admin consent ([#201](https://github.com/Unique-AG/connectors/issues/201)) ([39d89c2](https://github.com/Unique-AG/connectors/commit/39d89c20a416192526b3c3882fa3a9d33461c05a))


### Bug Fixes

* **sharepoint-connector:** remove unused tags variable from terraform ([39d89c2](https://github.com/Unique-AG/connectors/commit/39d89c20a416192526b3c3882fa3a9d33461c05a))
* **teams-mcp:** change accesses to ingested content ([#204](https://github.com/Unique-AG/connectors/issues/204)) ([fee642e](https://github.com/Unique-AG/connectors/commit/fee642e4ccdb9efaded966f379ae0268d5f6dda1))
* **teams-mcp:** output key vault secret arm resource id 🪪 ([#196](https://github.com/Unique-AG/connectors/issues/196)) ([bf669cb](https://github.com/Unique-AG/connectors/commit/bf669cb24e8994daa7bb6ff18d17e67e6a7528a3))

## 0.1.0 (2026-01-07)


### ⚠ BREAKING CHANGES

* **sharepoint-connector,outlook-mcp,factset-mcp:** all git tags no longer include the version 'v'. In a future version, all releases will also not include the v anymore.

### Features

* **sharepoint-connector,outlook-mcp,factset-mcp:** remove v in tags ([#168](https://github.com/Unique-AG/connectors/issues/168)) ([2f56700](https://github.com/Unique-AG/connectors/commit/2f5670000c968d8bf0e0051eeb47766f586c84cc))
* **teams-mcp:** initial implementation ([#179](https://github.com/Unique-AG/connectors/issues/179)) ([05738fb](https://github.com/Unique-AG/connectors/commit/05738fb79525c8a6c6c5bbf5d31d814458dc452e))
