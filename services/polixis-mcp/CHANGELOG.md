# Changelog

## [0.0.2](https://github.com/Unique-AG/connectors/compare/polixis-mcp@0.0.1...polixis-mcp@0.0.2) (2026-11-20)


### Bug Fixes

* **polixis-mcp:** spare the response cache's row locks and Polixis's quota (UN-28805) ([#1755](https://github.com/Unique-AG/connectors/issues/1755)) ([bee562e](https://github.com/Unique-AG/connectors/commit/bee562eaae7a6f95e0ee990494bc2c141b591970))


### Dependencies

* **deps:** bump authlib from 1.9.6 to 1.9.8 ([#1794](https://github.com/Unique-AG/connectors/issues/1794)) ([a737049](https://github.com/Unique-AG/connectors/commit/a737049e13c4ee3c25efbb95b9df7dcfd2284bd0))
* **deps:** bump cyclopts from 5.5.0 to 5.5.2 ([#1780](https://github.com/Unique-AG/connectors/issues/1780)) ([cac9f6f](https://github.com/Unique-AG/connectors/commit/cac9f6f1c2e94970c861c1fd128e8f0754769cb4))
* **deps:** bump httpx2 from 2.16.0 to 2.16.2 ([#1785](https://github.com/Unique-AG/connectors/issues/1785)) ([9613d9a](https://github.com/Unique-AG/connectors/commit/9613d9a5b39d60fcd92c0b6ad1f87a53e489c136))
* **deps:** bump numpy from 2.5.4 to 2.5.5 ([#1763](https://github.com/Unique-AG/connectors/issues/1763)) ([d5410b6](https://github.com/Unique-AG/connectors/commit/d5410b620f844177b4c6e6abb935da3350c3c4aa))
* **deps:** bump python-multipart from 0.0.33 to 0.0.34 ([#1795](https://github.com/Unique-AG/connectors/issues/1795)) ([e9308f1](https://github.com/Unique-AG/connectors/commit/e9308f15747922a00562d05a9bae9b0c084af7cc))
* **deps:** bump regex from 2026.11.9 to 2026.11.15 ([#1764](https://github.com/Unique-AG/connectors/issues/1764)) ([89a3c6a](https://github.com/Unique-AG/connectors/commit/89a3c6a7bdd760577bfb4cd981a7aec075d23d4c))
* **deps:** bump sqlalchemy from 2.1.8 to 2.1.9 ([#1786](https://github.com/Unique-AG/connectors/issues/1786)) ([9e0efdc](https://github.com/Unique-AG/connectors/commit/9e0efdc77b846a9b0531fafe37745b96a4f05b01))

## 0.0.1 (2026-11-18)


### Features

* **main:** add polixis-mcp, scaffolded with mcp-scaffold (UN-28805) ([#1738](https://github.com/Unique-AG/connectors/issues/1738)) ([5b67cb4](https://github.com/Unique-AG/connectors/commit/5b67cb480796da24c8e26b9feba486f1b57def00))
* **polixis-mcp,mcp-openapi,mcp-architecture:** answer the use cases within the Polixis request limit (UN-28805) ([#1740](https://github.com/Unique-AG/connectors/issues/1740)) ([5e41d65](https://github.com/Unique-AG/connectors/commit/5e41d65fee94c17404f2394903fe606b99d414ab))
* **polixis-mcp:** cache Polixis's answers at the transport, in a size-capped Postgres table (UN-28805) ([#1754](https://github.com/Unique-AG/connectors/issues/1754)) ([71f4a33](https://github.com/Unique-AG/connectors/commit/71f4a335c70606eb1af5ebc4fc176dd4b77af530))
* **polixis-mcp:** cache Polixis's answers for a configurable time, at most an hour (UN-28805) ([#1742](https://github.com/Unique-AG/connectors/issues/1742)) ([1918a49](https://github.com/Unique-AG/connectors/commit/1918a492482e630decccd4a17c362442849efa58))


### Dependencies

* **deps:** bump authlib from 1.9.5 to 1.9.6 ([#1748](https://github.com/Unique-AG/connectors/issues/1748)) ([8c32dc1](https://github.com/Unique-AG/connectors/commit/8c32dc11ed0da23f0249d5698d8f3ff3e9da2afa))
* **deps:** bump azurerm from 5.12.0 to 5.14.0 ([#1746](https://github.com/Unique-AG/connectors/issues/1746)) ([021f4d5](https://github.com/Unique-AG/connectors/commit/021f4d5172a83d092fff1a8ca6a5e30b0394a411))
* **deps:** bump cyclopts from 5.4.2 to 5.5.0 ([#1749](https://github.com/Unique-AG/connectors/issues/1749)) ([537e27b](https://github.com/Unique-AG/connectors/commit/537e27be4b64c3c51a281a9f8bbab455529dd1e0))
* **deps:** bump email-validator from 2.3.0 to 2.4.0 ([#1750](https://github.com/Unique-AG/connectors/issues/1750)) ([79df80f](https://github.com/Unique-AG/connectors/commit/79df80f6ed1ba3d9a7e52c7cae5efc0f7c0e32b6))
* **deps:** bump pydantic-settings from 2.16.2 to 2.16.3 ([#1720](https://github.com/Unique-AG/connectors/issues/1720)) ([1d248c1](https://github.com/Unique-AG/connectors/commit/1d248c177601907f67d3bb0af5721cf4fe5e0da5))
* **deps:** bump python from 3.14-slim-trixie@51dafde81dbd to 3.14-slim-trixie@9aaa474097d0 ([#1745](https://github.com/Unique-AG/connectors/issues/1745)) ([a2acb18](https://github.com/Unique-AG/connectors/commit/a2acb18f074eb25cbd690b09673ee469f6a9c249))
