# Changelog

## [2.0.0-alpha.16](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@v2.0.0-alpha.15...sharepoint-connector@v2.0.0-alpha.16) (2025-11-20)


### Features

* **sharepoint-connector:** added skip ingestion config ([#124](https://github.com/Unique-AG/connectors/issues/124)) ([41f8138](https://github.com/Unique-AG/connectors/commit/41f8138b35f229fe29984d35b50abbec2f39337d))
* **sharepoint-connector:** expose storeInternally as environment variable ([#121](https://github.com/Unique-AG/connectors/issues/121)) ([a30df30](https://github.com/Unique-AG/connectors/commit/a30df3068881311205932b92f5630018e4630fbe))
* **sharepoint-connector:** Implemented max ingested files environment variable ([#122](https://github.com/Unique-AG/connectors/issues/122)) ([efef764](https://github.com/Unique-AG/connectors/commit/efef764b249ddb9820b338b5ff22e799c02309f7))


### Bug Fixes

* **sharepoint-connector:** add missing onResponseError ([#125](https://github.com/Unique-AG/connectors/issues/125)) ([59ea328](https://github.com/Unique-AG/connectors/commit/59ea328cb030ee05efb9f915f1dfc5be2583cd07))

## [2.0.0-alpha.15](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@v2.0.0-alpha.14...sharepoint-connector@v2.0.0-alpha.15) (2025-11-19)


### Bug Fixes

* **sharepoint-connector:** prefix create groups with site ID ([#120](https://github.com/Unique-AG/connectors/issues/120)) ([cd38551](https://github.com/Unique-AG/connectors/commit/cd385511d120f84fb48dff677d3e3d0a2254aed0))
* **sharepoint-connector:** preformat terraform output ([#117](https://github.com/Unique-AG/connectors/issues/117)) ([91d7acb](https://github.com/Unique-AG/connectors/commit/91d7acbb2a56492dd30ce6ab453e5f58e917bc89))

## [2.0.0-alpha.14](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@v2.0.0-alpha.13...sharepoint-connector@v2.0.0-alpha.14) (2025-11-17)


### Bug Fixes

* **sharepoint-connector:** keep permissions of re-ingested files ([#115](https://github.com/Unique-AG/connectors/issues/115)) ([d8cbb0c](https://github.com/Unique-AG/connectors/commit/d8cbb0ccf1508d78eb0a736a9c797cbc789fedf7))

## [2.0.0-alpha.13](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@v2.0.0-alpha.12...sharepoint-connector@v2.0.0-alpha.13) (2025-11-17)


### Features

* **sharepoint-connector:** implement files & folders permissions sync ([#105](https://github.com/Unique-AG/connectors/issues/105)) ([f219909](https://github.com/Unique-AG/connectors/commit/f219909849649c8f8280067b2fd08e8818b8ba01))
* **sharepoint-connector:** implement path based ingestion by manually creating the scopes and ingesting by scopeId ([#91](https://github.com/Unique-AG/connectors/issues/91)) ([3652046](https://github.com/Unique-AG/connectors/commit/365204691d61e94896a47908c79d91ccdfa3b937))

## [2.0.0-alpha.12](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@v2.0.0-alpha.11...sharepoint-connector@v2.0.0-alpha.12) (2025-11-13)


### Features

* **sharepoint-connector:** added drive id to logs ([#103](https://github.com/Unique-AG/connectors/issues/103)) ([241a923](https://github.com/Unique-AG/connectors/commit/241a92376cdd0aa7d2d99845f6e911b2725f32e6))
* **sharepoint-connector:** allow auto-creating key and certificate ([#104](https://github.com/Unique-AG/connectors/issues/104)) ([0bb5b95](https://github.com/Unique-AG/connectors/commit/0bb5b95326cbd5b763bea2beb81664f8d7bf525a))
* **sharepoint-connector:** implement groups syncing from SharePoint to Unique ([#93](https://github.com/Unique-AG/connectors/issues/93)) ([1d94465](https://github.com/Unique-AG/connectors/commit/1d94465dcede85dad3e3a6c962c2c3ef90c3c60a))
* **sharepoint-connector:** support for Unique API auth modes ([#101](https://github.com/Unique-AG/connectors/issues/101)) ([743999e](https://github.com/Unique-AG/connectors/commit/743999edb48554a8378a43b822a1a6c2e2aa4e48))
* **sharepoint-connector:** UniqueFilesService simple implementation ([#102](https://github.com/Unique-AG/connectors/issues/102)) ([974d778](https://github.com/Unique-AG/connectors/commit/974d7788ba3b5e23bb60dc678f291168ee043ef6))

## [2.0.0-alpha.11](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@v2.0.0-alpha.10...sharepoint-connector@v2.0.0-alpha.11) (2025-11-09)


### Features

* **sharepoint-connector:** add helm chart install validations ([#89](https://github.com/Unique-AG/connectors/issues/89)) ([1f96305](https://github.com/Unique-AG/connectors/commit/1f963052c63f0c365bd8568dd7c492d13a34de00))
* **sharepoint-connector:** clean unnecessary words from the ingested file paths ([#92](https://github.com/Unique-AG/connectors/issues/92)) ([d7890b6](https://github.com/Unique-AG/connectors/commit/d7890b6cd98e958c196a48ca7df3bb47a531377f))


### Bug Fixes

* **sharepoint-connector:** explanation for setting spc manual private key secret ([#98](https://github.com/Unique-AG/connectors/issues/98)) ([8bdd503](https://github.com/Unique-AG/connectors/commit/8bdd503fd2aac0bbb11b15c3daa531955fe9b112))

## [2.0.0-alpha.10](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@v2.0.0-alpha.9...sharepoint-connector@v2.0.0-alpha.10) (2025-11-03)


### Features

* **sharepoint-connector:** add certificate support ([#84](https://github.com/Unique-AG/connectors/issues/84)) ([a789694](https://github.com/Unique-AG/connectors/commit/a7896948047ec292f4c6f9105921358e5cdadb17))
* **sharepoint-connector:** added workflow actions from template-mcp-ci to sharepoint-connector ([#76](https://github.com/Unique-AG/connectors/issues/76)) ([c883fbe](https://github.com/Unique-AG/connectors/commit/c883fbe6e908797d2919306f9d4692e8da3808e1))
* **sharepoint-connector:** expose cron job on env variable ([#75](https://github.com/Unique-AG/connectors/issues/75)) ([40ddc11](https://github.com/Unique-AG/connectors/commit/40ddc11c05fc747b8b3698a532f02ed4482cfac5))
* **sharepoint-connector:** fixed hairpinning ([#87](https://github.com/Unique-AG/connectors/issues/87)) ([1b98d5d](https://github.com/Unique-AG/connectors/commit/1b98d5d7ea3409ddd9774a5925b4cd79437e2a9e))
* **sharepoint-connector:** implement certificate authentication for SharePoint ([#82](https://github.com/Unique-AG/connectors/issues/82)) ([56e3e44](https://github.com/Unique-AG/connectors/commit/56e3e4496f846044e74f3db274807b9ac9c3c096))
* **sharepoint-connector:** implement configurable ingestion folder ([#83](https://github.com/Unique-AG/connectors/issues/83)) ([492f9e0](https://github.com/Unique-AG/connectors/commit/492f9e039d205c23a2e23cacc7621f69d4163ae9))
* **sharepoint-connector:** permissions fetching ([#81](https://github.com/Unique-AG/connectors/issues/81)) ([dd124f5](https://github.com/Unique-AG/connectors/commit/dd124f5400d96924ee2b8b030bb1a8c8b265e463))
* **sharepoint-connector:** revert OIDC token debugging changes ([#77](https://github.com/Unique-AG/connectors/issues/77)) ([72f647f](https://github.com/Unique-AG/connectors/commit/72f647f24007c583ffe11af1e80dd42a7d534ab0))
* **spc:** read drive item web url from listItem instead of item so we have a nice file path for knowledgebase ([#80](https://github.com/Unique-AG/connectors/issues/80)) ([c695267](https://github.com/Unique-AG/connectors/commit/c6952671290c06eef32019b4b95a439aa40f94e4))


### Bug Fixes

* **sharepoint-connector:** add certificate resources ([#88](https://github.com/Unique-AG/connectors/issues/88)) ([1b2c844](https://github.com/Unique-AG/connectors/commit/1b2c844487801592f9757d1e05f59205c90793e4))
* **sharepoint-connector:** do not request Graph API token multiple times ([#79](https://github.com/Unique-AG/connectors/issues/79)) ([528b6a2](https://github.com/Unique-AG/connectors/commit/528b6a226c736a4f7119778915309e896248e2db))

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
