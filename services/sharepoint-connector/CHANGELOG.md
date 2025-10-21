# Changelog

## [2.0.0-alpha.9](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@v2.0.0-alpha.8...sharepoint-connector@v2.0.0-alpha.9) (2025-10-20)


### Bug Fixes

* **sharepoint-connector:** log properties from JWT via OIDC for QA debugging ([#73](https://github.com/Unique-AG/connectors/issues/73)) ([3711446](https://github.com/Unique-AG/connectors/commit/3711446fca4614c7476c518d4b1bc68a26d8cc0a))

## [2.0.0-alpha.8](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@v2.0.0-alpha.7...sharepoint-connector@v2.0.0-alpha.8) (2025-10-20)


### Bug Fixes

* **sharepoint-connector:** fix caching for OIDC auth strategy ([#71](https://github.com/Unique-AG/connectors/issues/71)) ([82aed89](https://github.com/Unique-AG/connectors/commit/82aed89c14d644c3021d614a690dc7cb51b3bd17))

## [2.0.0-alpha.7](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@v2.0.0-alpha.6...sharepoint-connector@v2.0.0-alpha.7) (2025-10-20)


### Features

* **sharepoint-connector:** Test OIDC token eligibility for SP REST V1 API ([#67](https://github.com/Unique-AG/connectors/issues/67)) ([c76a2d6](https://github.com/Unique-AG/connectors/commit/c76a2d655add7d863ae6414fdb1bac1aa92549b6))


### Bug Fixes

* **factset:** upgrade Prisma to fix incompatible Prisma versions ([#69](https://github.com/Unique-AG/connectors/issues/69)) ([2586805](https://github.com/Unique-AG/connectors/commit/2586805e33fcbf810a1b7d8e588288b2fbc4d76f))

## [2.0.0-alpha.6](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@v2.0.0-alpha.5...sharepoint-connector@v2.0.0-alpha.6) (2025-10-17)


### Features

* **sharepoint-connector:** Implemented ASPX file processing and scanning of Lists (SitePages list specifically) ([#64](https://github.com/Unique-AG/connectors/issues/64)) ([6944066](https://github.com/Unique-AG/connectors/commit/6944066ce08126a0e2da910f0f63d9f21fa24b53))

## [2.0.0-alpha.5](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@v2.0.0-alpha.4...sharepoint-connector@v2.0.0-alpha.5) (2025-10-14)


### Features

* **sharepoint-connector:** fixed path based ingestion ([#62](https://github.com/Unique-AG/connectors/issues/62)) ([c606b32](https://github.com/Unique-AG/connectors/commit/c606b32791dea0aa88968007961f8e03c0adaeb0))


### Bug Fixes

* **spc:** clarify sites parameter ([#59](https://github.com/Unique-AG/connectors/issues/59)) ([9af2eef](https://github.com/Unique-AG/connectors/commit/9af2eefa124d8b0e14288d438893c796516d8825))
* **spc:** support graph roles properly ([#58](https://github.com/Unique-AG/connectors/issues/58)) ([331227d](https://github.com/Unique-AG/connectors/commit/331227d12a55be2bd89269ca0efac8ba60b52937))

## [2.0.0-alpha.4](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@v2.0.0-alpha.3...sharepoint-connector@v2.0.0-alpha.4) (2025-10-08)


### Bug Fixes

* **sharepoint-connector:** fix non-string envs and avoid error swallowing ([#57](https://github.com/Unique-AG/connectors/issues/57)) ([bf9079a](https://github.com/Unique-AG/connectors/commit/bf9079a1aa4bc73f7040b3f3650931b8f9ed5935))
* **spc:** provider naming mismatch ([#54](https://github.com/Unique-AG/connectors/issues/54)) ([f2472bc](https://github.com/Unique-AG/connectors/commit/f2472bcc107fc9b2573005fc6629c80fecac2333))

## [2.0.0-alpha.3](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@v2.0.0-alpha.2...sharepoint-connector@v2.0.0-alpha.3) (2025-10-07)


### Bug Fixes

* **sharepoint-connector:** fix base url for UNIQUE_HTTP_CLIENT ([#49](https://github.com/Unique-AG/connectors/issues/49)) ([d6d45dc](https://github.com/Unique-AG/connectors/commit/d6d45dce6ec1b2d2e5ec3ba0999eab0c6e2942a0))
* **spc:** release as alpha.3 ([#52](https://github.com/Unique-AG/connectors/issues/52)) ([6067a8c](https://github.com/Unique-AG/connectors/commit/6067a8c3289478ce06a3a8975109be51ef082961))

## [2.0.0-alpha.2](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@v2.0.0-alpha.1...sharepoint-connector@v2.0.0-alpha.2) (2025-10-07)


### Features

* **outlook:** switch to Drizzle ORM ([#30](https://github.com/Unique-AG/connectors/issues/30)) ([26261c3](https://github.com/Unique-AG/connectors/commit/26261c3d28ec98296a46438e39953b43b3b817eb))
* restructure infra components to streamline ([#28](https://github.com/Unique-AG/connectors/issues/28)) ([21245a9](https://github.com/Unique-AG/connectors/commit/21245a9c933816be9e29df183444fc2f3b6c5d3e))
* **sharepoint-connector:** migrate and integrate sharepoint-connector service into monorepo ([#23](https://github.com/Unique-AG/connectors/issues/23)) ([c73fbec](https://github.com/Unique-AG/connectors/commit/c73fbec2136acf5136f52dae37c7a346c89b6989))
* **sharepoint-connector:** release as alpha ([#45](https://github.com/Unique-AG/connectors/issues/45)) ([030b72d](https://github.com/Unique-AG/connectors/commit/030b72d04119b3f8b1eab8c886c7828fa7448ca7))
* **sharepoint-connector:** UN-13757 Sharepoint  connector existing business logic ([#33](https://github.com/Unique-AG/connectors/issues/33)) ([bf0f41a](https://github.com/Unique-AG/connectors/commit/bf0f41a76fa2042a5d5fa0a73bf9b7dd6d4d1afc))
* **spc:** add helm chart ([#37](https://github.com/Unique-AG/connectors/issues/37)) ([962c6b2](https://github.com/Unique-AG/connectors/commit/962c6b2fdf1f632983e18d0aa244b46a78fa4f05))
* **spc:** add terraform secret for azure ([#36](https://github.com/Unique-AG/connectors/issues/36)) ([f444cb0](https://github.com/Unique-AG/connectors/commit/f444cb0863f54c873b0247ad1b401c7395ec2b7d))
* **spc:** remove unused permissions ([#40](https://github.com/Unique-AG/connectors/issues/40)) ([dc2e05e](https://github.com/Unique-AG/connectors/commit/dc2e05e02f562809ac16dae5e170c859f6eb0c98))
* **spcv2:** output client id ([#34](https://github.com/Unique-AG/connectors/issues/34)) ([027cd87](https://github.com/Unique-AG/connectors/commit/027cd87108cfe344c257600213dd27b3192be521))
* **terraform:** refactor all modules into folders ([69b07e0](https://github.com/Unique-AG/connectors/commit/69b07e05f6277fcd08d98df1691cd7833b9c2e4d))


### Bug Fixes

* **spc:** add corepack tmp volume ([#39](https://github.com/Unique-AG/connectors/issues/39)) ([ed4f880](https://github.com/Unique-AG/connectors/commit/ed4f880881065c8f34f3196a3754d72c6a91374a))
* **spc:** minor inconsistencies of helm chart ([#47](https://github.com/Unique-AG/connectors/issues/47)) ([1909710](https://github.com/Unique-AG/connectors/commit/1909710b49b215db4f4bc244ac0422e8c9cf7187))
