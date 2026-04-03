# Changelog

## [2.0.0-alpha.5](https://github.com/Unique-AG/connectors/compare/confluence-connector@2.0.0-alpha.4...confluence-connector@2.0.0-alpha.5) (2026-04-03)


### Features

* **confluence-connector:** add metrics and Grafana dashboard ([#395](https://github.com/Unique-AG/connectors/issues/395)) ([cb765d5](https://github.com/Unique-AG/connectors/commit/cb765d5a6897073cc566eed3a6a7e6676e625ef1))


### Bug Fixes

* **confluence-connector:** allow deletion guard to pass when new files are being added ([#368](https://github.com/Unique-AG/connectors/issues/368)) ([b57683c](https://github.com/Unique-AG/connectors/commit/b57683c27d13c32c847758cb77be52c65a00dcfa))
* **confluence-connector:** clean up registered content after failed upload or finalization ([#381](https://github.com/Unique-AG/connectors/issues/381)) ([b78cebb](https://github.com/Unique-AG/connectors/commit/b78cebb2017726f653901392a2561b618399d6a1))

## [2.0.0-alpha.4](https://github.com/Unique-AG/connectors/compare/confluence-connector@2.0.0-alpha.3...confluence-connector@2.0.0-alpha.4) (2026-03-17)


### Features

* **confluence-connector:** file attachment ingestion ([#358](https://github.com/Unique-AG/connectors/issues/358)) ([69cdaff](https://github.com/Unique-AG/connectors/commit/69cdaff68bd972ec84e09e21d1cbc630239e3d42))

## [2.0.0-alpha.3](https://github.com/Unique-AG/connectors/compare/confluence-connector@2.0.0-alpha.2...confluence-connector@2.0.0-alpha.3) (2026-03-16)


### Bug Fixes

* **confluence-connector:** align v2 with v1 for DC space types, label sorting, and blog posts ([#350](https://github.com/Unique-AG/connectors/issues/350)) ([73698f3](https://github.com/Unique-AG/connectors/commit/73698f31b707e0f9cd56305bf9ad10acb667199b))
* **confluence-connector:** bring in the totalFilesInUnique deletion guard logic from sharepoint-connector ([#347](https://github.com/Unique-AG/connectors/issues/347)) ([af98e39](https://github.com/Unique-AG/connectors/commit/af98e390dad18624987d086e9d3e18909a294e2e))

## [2.0.0-alpha.2](https://github.com/Unique-AG/connectors/compare/confluence-connector@2.0.0-alpha.1...confluence-connector@2.0.0-alpha.2) (2026-03-10)


### Bug Fixes

* **confluence-connector:** correctWriteUrl when using cluster_local ([#345](https://github.com/Unique-AG/connectors/issues/345)) ([2bde377](https://github.com/Unique-AG/connectors/commit/2bde37745f499c1d2b88ffbe9ad8e7439e12ff09))

## [2.0.0-alpha.1](https://github.com/Unique-AG/connectors/compare/confluence-connector@2.0.0-alpha.0...confluence-connector@2.0.0-alpha.1) (2026-03-10)


### ⚠ BREAKING CHANGES

* **sharepoint-connector,outlook-mcp,factset-mcp:** all git tags no longer include the version 'v'. In a future version, all releases will also not include the v anymore.

### Features

* **confluence-connector,ci,main,deps:** scaffold NestJS project with tenant configuration loading ([#258](https://github.com/Unique-AG/connectors/issues/258)) ([63713b7](https://github.com/Unique-AG/connectors/commit/63713b7dc0d260ceb5e29ceb32196adc4147e717))
* **confluence-connector,deps:** implement multi-tenancy and confluence scanning for DC and Cloud ([#284](https://github.com/Unique-AG/connectors/issues/284)) ([e0f8703](https://github.com/Unique-AG/connectors/commit/e0f87038caf4825d390d51307a8270019183b501))
* **confluence-connector,unique-api,utils,deps:** implement ingestion pipeline ([#305](https://github.com/Unique-AG/connectors/issues/305)) ([7d2c64c](https://github.com/Unique-AG/connectors/commit/7d2c64c1f4248e06a822a7d827715c4ae001eeec))
* **confluence-connector:** add Terraform module for Key Vault secret provisioning ([#339](https://github.com/Unique-AG/connectors/issues/339)) ([ce2241e](https://github.com/Unique-AG/connectors/commit/ce2241ebb8614640f3c7cdb5a6e35a2f17c344a3))
* **sharepoint-connector,outlook-mcp,factset-mcp:** remove v in tags ([#168](https://github.com/Unique-AG/connectors/issues/168)) ([2f56700](https://github.com/Unique-AG/connectors/commit/2f5670000c968d8bf0e0051eeb47766f586c84cc))
