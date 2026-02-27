# Changelog

## [2.2.0](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@2.1.1...sharepoint-connector@2.2.0) (2026-02-27)


### Features

* **sharepoint-connector:** align docs and add PUBDOC page mappings ([#303](https://github.com/Unique-AG/connectors/issues/303)) ([0229e04](https://github.com/Unique-AG/connectors/commit/0229e045b6dd2717910b8800763b71102c11f1e9))


### Bug Fixes

* **sharepoint-connector:** fill size for drive items ([#296](https://github.com/Unique-AG/connectors/issues/296)) ([fe54e5d](https://github.com/Unique-AG/connectors/commit/fe54e5dd81728466531a60f8ffd70ae34b19f021))
* **sharepoint-connector:** update the link to configuration list csv template to a non-encoded local path ([#309](https://github.com/Unique-AG/connectors/issues/309)) ([fffa3b2](https://github.com/Unique-AG/connectors/commit/fffa3b200bab1823fa046e96a00fb34f593aec23))

## [2.1.1](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@2.1.0...sharepoint-connector@2.1.1) (2026-02-16)


### Bug Fixes

* **sharepoint-connector:** resolve externalId conflict when folders move within a drive ([#274](https://github.com/Unique-AG/connectors/issues/274)) ([98d44fd](https://github.com/Unique-AG/connectors/commit/98d44fd346191d69096d8966be65f365fb0e657d))

## [2.1.0](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@2.0.0...sharepoint-connector@2.1.0) (2026-02-09)


### Features

* **sharepoint-connector:** trigger release of 2.0.1 ([#262](https://github.com/Unique-AG/connectors/issues/262)) ([85eedae](https://github.com/Unique-AG/connectors/commit/85eedae503b60bd66db89b0c2c8ac8d2a5991d11))

## [2.0.0](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@2.0.0-beta.13...sharepoint-connector@2.0.0) (2026-02-05)


### Features

* **sharepoint-connector:** add HTTP proxy support ([#242](https://github.com/Unique-AG/connectors/issues/242)) ([cc852fc](https://github.com/Unique-AG/connectors/commit/cc852fcb19d62774b7779a46a9f3075b89c9d5bc))
* **sharepoint-connector:** aggregate group permissions for site and library scopes ([#249](https://github.com/Unique-AG/connectors/issues/249)) ([1c96175](https://github.com/Unique-AG/connectors/commit/1c96175297ff32fcbe06f9b6750f019433b746d4))
* **sharepoint-connector:** detect and migrate scopes when root scope ID changes ([#246](https://github.com/Unique-AG/connectors/issues/246)) ([5d2dbe3](https://github.com/Unique-AG/connectors/commit/5d2dbe3e487f0efb549fb67a19759815d4ca9d6b))
* **sharepoint-connector:** Implement Non-Secret Configuration Emission for SharePoint Connector ([#237](https://github.com/Unique-AG/connectors/issues/237)) ([5eb9e4e](https://github.com/Unique-AG/connectors/commit/5eb9e4e7f1741c3381b30ccb33320b4fb7565035))


### Miscellaneous Chores

* **sharepoint-connector:** officially release SPC 2.0.0 ([#257](https://github.com/Unique-AG/connectors/issues/257)) ([987552f](https://github.com/Unique-AG/connectors/commit/987552f29b3fe6957ae51ca81d89b7e724756200))

## [2.0.0-beta.13](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@2.0.0-beta.12...sharepoint-connector@2.0.0-beta.13) (2026-01-28)


### Bug Fixes

* **sharepoint-connector:** give write access to the root scope to fix issue where we fail to create scopes due to missing access ([#240](https://github.com/Unique-AG/connectors/issues/240)) ([1753561](https://github.com/Unique-AG/connectors/commit/1753561f39217a64ca3a98a807552f29dc9c195e))

## [2.0.0-beta.12](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@2.0.0-beta.11...sharepoint-connector@2.0.0-beta.12) (2026-01-22)


### Features

* **sharepoint-connector:** Improve scope deduplication and add ownership validation for config site ([#222](https://github.com/Unique-AG/connectors/issues/222)) ([30558cb](https://github.com/Unique-AG/connectors/commit/30558cb82f268178feed928a40097318ee7ec0fb))
* **sharepoint-connector:** Use SharePoint list ID instead of display name for configuration ([#228](https://github.com/Unique-AG/connectors/issues/228)) ([870d126](https://github.com/Unique-AG/connectors/commit/870d126f00170ad924c8d44492f171d6ccd01ddf))

## [2.0.0-beta.11](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@2.0.0-beta.10...sharepoint-connector@2.0.0-beta.11) (2026-01-21)


### Features

* **sharepoint-connector:** change the external id for the scope where we ingest the site to be prefixed by site not root ([#218](https://github.com/Unique-AG/connectors/issues/218)) ([bad2520](https://github.com/Unique-AG/connectors/commit/bad2520b0953b4618b1b8b6e2c33cd497a7b3ce2))

## [2.0.0-beta.10](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@2.0.0-beta.9...sharepoint-connector@2.0.0-beta.10) (2026-01-20)


### Features

* **sharepoint-connector:** sharepoint connector external site config ([#193](https://github.com/Unique-AG/connectors/issues/193)) ([e2973d9](https://github.com/Unique-AG/connectors/commit/e2973d9be537252ea23c8cadb8f9393168a2109b))
* **teams-mcp:** auto admin consent ([#201](https://github.com/Unique-AG/connectors/issues/201)) ([39d89c2](https://github.com/Unique-AG/connectors/commit/39d89c20a416192526b3c3882fa3a9d33461c05a))


### Bug Fixes

* **sharepoint-connector:** remove default network policy block in values.yaml ([#217](https://github.com/Unique-AG/connectors/issues/217)) ([7720852](https://github.com/Unique-AG/connectors/commit/7720852c3051b56af9c73df0501cd06f0f7db85d))
* **sharepoint-connector:** remove unused tags variable from terraform ([39d89c2](https://github.com/Unique-AG/connectors/commit/39d89c20a416192526b3c3882fa3a9d33461c05a))

## [2.0.0-beta.9](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@2.0.0-beta.8...sharepoint-connector@2.0.0-beta.9) (2026-01-09)


### Features

* **sharepoint-connector:** add configurable file and scope inheritance ([#165](https://github.com/Unique-AG/connectors/issues/165)) ([dc03134](https://github.com/Unique-AG/connectors/commit/dc031342b2d7a280a155b7188d7fee25f1aa15be))


### Bug Fixes

* **sharepoint-connector:** Improve permissions sync error handling and reliability ([#197](https://github.com/Unique-AG/connectors/issues/197)) ([5129ce5](https://github.com/Unique-AG/connectors/commit/5129ce5339257afb5dbfee916c64e25c010c9842))
* **sharepoint-connector:** removed sensitive data from warning log ([#186](https://github.com/Unique-AG/connectors/issues/186)) ([9d71b95](https://github.com/Unique-AG/connectors/commit/9d71b95885c5ddcae235fc79b4bd8fca9b0658a3))

## [2.0.0-beta.8](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@2.0.0-beta.7...sharepoint-connector@2.0.0-beta.8) (2025-12-11)


### ⚠ BREAKING CHANGES

* **sharepoint-connector:** restructure auth config and fix schema issues ([#178](https://github.com/Unique-AG/connectors/issues/178))
    - tenantId moved from sharepoint.auth to sharepoint level     - Move tenantId from auth section to sharepoint root for clarity
    - Remove unused oidc and client-secret auth modes (only certificate
    supported)
        - Change clientId from nullable to required string with default
    - Fix maxFileSizeBytes description (was incorrectly "max files to scan")
        - Remove deprecated maxFilesToScan from schema
        - Fix misplaced additionalProperties in graph schema
* **sharepoint-connector:** removes settings from helm chart (but they werent used)

### Features

* **sharepoint-connector:** add certificate thumbprint outputs ([b439004](https://github.com/Unique-AG/connectors/commit/b43900475ad2e43762d7fc592c201b4ee862ee73))
* **sharepoint-connector:** stream file to storage instead of buffering ([#172](https://github.com/Unique-AG/connectors/issues/172)) ([6dcd54a](https://github.com/Unique-AG/connectors/commit/6dcd54a911e1f934c4a7733307d051e32f61d52a))


### Bug Fixes

* **ci:** use certificate-identity-regexp for cosign signature ([b439004](https://github.com/Unique-AG/connectors/commit/b43900475ad2e43762d7fc592c201b4ee862ee73))
* **sharepoint-connector:** restructure auth config and fix schema issues ([#178](https://github.com/Unique-AG/connectors/issues/178)) ([b439004](https://github.com/Unique-AG/connectors/commit/b43900475ad2e43762d7fc592c201b4ee862ee73))
* **sharepoint-connector:** store internally enabled by default ([#182](https://github.com/Unique-AG/connectors/issues/182)) ([109d1fd](https://github.com/Unique-AG/connectors/commit/109d1fdf8f9551441f931180b92ff4938b534331))


### Documentation

* add signed artifact verification instructions ([b439004](https://github.com/Unique-AG/connectors/commit/b43900475ad2e43762d7fc592c201b4ee862ee73))


### Miscellaneous Chores

* **sharepoint-connector:** remove keypassword and sha256 thumbprint ([b439004](https://github.com/Unique-AG/connectors/commit/b43900475ad2e43762d7fc592c201b4ee862ee73))

## [2.0.0-beta.7](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@v2.0.0-beta.6...sharepoint-connector@2.0.0-beta.7) (2025-12-10)


### ⚠ BREAKING CHANGES

* **sharepoint-connector,outlook-mcp,factset-mcp:** all git tags no longer include the version 'v'. In a future version, all releases will also not include the v anymore.

### Features

* **sharepoint-connector,outlook-mcp,factset-mcp:** remove v in tags ([#168](https://github.com/Unique-AG/connectors/issues/168)) ([2f56700](https://github.com/Unique-AG/connectors/commit/2f5670000c968d8bf0e0051eeb47766f586c84cc))
* **sharepoint-connector:** add sync failure alert ([#169](https://github.com/Unique-AG/connectors/issues/169)) ([e8c8980](https://github.com/Unique-AG/connectors/commit/e8c8980e2784d2c1e7c4281f77618a9431e8d7ba))
* **sharepoint-connector:** UN-15207 Added cleanup step to delete ingested files if upload fails ([#160](https://github.com/Unique-AG/connectors/issues/160)) ([afcc182](https://github.com/Unique-AG/connectors/commit/afcc1821e87387b8fc83810a44670fe4067f750c))


### Bug Fixes

* **sharepoint-connector:** shrink alert detection windows ([#166](https://github.com/Unique-AG/connectors/issues/166)) ([7a31956](https://github.com/Unique-AG/connectors/commit/7a31956534c43837b0900e8b8ef622130ff67911))

## [2.0.0-beta.6](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@v2.0.0-beta.5...sharepoint-connector@v2.0.0-beta.6) (2025-12-08)


### Bug Fixes

* **sharepoint-connector:** Removed hardcoded value from sitePages pre-processing checks ([#161](https://github.com/Unique-AG/connectors/issues/161)) ([0ee6a8b](https://github.com/Unique-AG/connectors/commit/0ee6a8b9c4aa8c88bd5a53319b6dbafb6eeba8ff))

## [2.0.0-beta.5](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@v2.0.0-beta.4...sharepoint-connector@v2.0.0-beta.5) (2025-12-08)


### Bug Fixes

* **sharepoint-connector:** prefix external ids with siteId to obey constraint ([#157](https://github.com/Unique-AG/connectors/issues/157)) ([19d27f0](https://github.com/Unique-AG/connectors/commit/19d27f0962270b8da592bbbaeb54bdf59262ef1b))

## [2.0.0-beta.4](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@v2.0.0-beta.3...sharepoint-connector@v2.0.0-beta.4) (2025-12-08)


### Features

* **sharepoint connector:** un-14015 improvements of code: error messages, chunking, etc ([#151](https://github.com/Unique-AG/connectors/issues/151)) ([1be3640](https://github.com/Unique-AG/connectors/commit/1be36404b5ec89d03704ba801d50f4a396f29a80))
* **sharepoint-connector:** add dashboard and two basic alerts 🔔  ([#144](https://github.com/Unique-AG/connectors/issues/144)) ([2c9cd73](https://github.com/Unique-AG/connectors/commit/2c9cd73e353e5c4d8ec36138ba9c1936336b080c))
* **sharepoint-connector:** add ingestion config env variable ([#149](https://github.com/Unique-AG/connectors/issues/149)) ([5f94f79](https://github.com/Unique-AG/connectors/commit/5f94f79cf3ab8667337971147d861e4fc1694ed8))
* **sharepoint-connector:** add runbooks to alerts ([#150](https://github.com/Unique-AG/connectors/issues/150)) ([55c3558](https://github.com/Unique-AG/connectors/commit/55c3558a6472696a322b51744864375df6bde97d))
* **sharepoint-connector:** added uuidv4 validation for siteIds ([#155](https://github.com/Unique-AG/connectors/issues/155)) ([3bd6432](https://github.com/Unique-AG/connectors/commit/3bd6432544eb9797b133dc299bf92301c61ba43c))
* **sharepoint-connector:** prevent accidental deletion of all files ([#153](https://github.com/Unique-AG/connectors/issues/153)) ([d9a7fa5](https://github.com/Unique-AG/connectors/commit/d9a7fa545d18944c17982d035780d24d6443f482))
* **sharepoint-connector:** set externalId on SharePoint scopes ([#141](https://github.com/Unique-AG/connectors/issues/141)) ([aadb96e](https://github.com/Unique-AG/connectors/commit/aadb96ec8080f9dabb74eb8ca8bac3ece05a87b0))


### Bug Fixes

* **sharepoint-connector:** do not set externalId above root scope ([#156](https://github.com/Unique-AG/connectors/issues/156)) ([1e491a4](https://github.com/Unique-AG/connectors/commit/1e491a477aceb5f49f57d2e6858616245095c79c))
* **sharepoint-connector:** metrics path extractor improvements ([#146](https://github.com/Unique-AG/connectors/issues/146)) ([09fb08b](https://github.com/Unique-AG/connectors/commit/09fb08b95e80e28d4bf8b5fd6779a79678007d89))
* **sharepoint-connector:** retry SP REST API batch requests ([#148](https://github.com/Unique-AG/connectors/issues/148)) ([fe772b1](https://github.com/Unique-AG/connectors/commit/fe772b12f3de5e503103435ff854a6546757ae65))
* **sharepoint-connector:** revert "experimental re-write of MS Graph API client ([#140](https://github.com/Unique-AG/connectors/issues/140))" ([#143](https://github.com/Unique-AG/connectors/issues/143)) ([021e50c](https://github.com/Unique-AG/connectors/commit/021e50c5df93d80cb95cf7a0a47ea391d38926e8))

## [2.0.0-beta.3](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@v2.0.0-beta.2...sharepoint-connector@v2.0.0-beta.3) (2025-12-01)


### Features

* **sharepoint-connector:** experimental re-write of MS Graph API client ([#140](https://github.com/Unique-AG/connectors/issues/140)) ([09df586](https://github.com/Unique-AG/connectors/commit/09df58662aba21ea790aa0a90c87ef3713690c99))

## [2.0.0-beta.2](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@v2.0.0-beta.1...sharepoint-connector@v2.0.0-beta.2) (2025-12-01)


### Features

* **sharepoint-connector:** add basic metrics ([#137](https://github.com/Unique-AG/connectors/issues/137)) ([51f5102](https://github.com/Unique-AG/connectors/commit/51f5102eb6d24141e92ff9062c8dc9c15c9c1193))

## [2.0.0-beta.1](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@v2.0.0-alpha.17...sharepoint-connector@v2.0.0-beta.1) (2025-11-28)


### Features

* **sharepoint-connector:** Added metadata when we ingest a file ([#130](https://github.com/Unique-AG/connectors/issues/130)) ([7b63078](https://github.com/Unique-AG/connectors/commit/7b630785708ff14d4f4b0b29df06f83422ac03dd))
* **sharepoint-connector:** Smear and Redact logs ([#136](https://github.com/Unique-AG/connectors/issues/136)) ([de63672](https://github.com/Unique-AG/connectors/commit/de63672ac108b44e28b02573e957555438fa5e32))
* **sharepoint-connector:** unify root folder config for both ingestion modes ([#133](https://github.com/Unique-AG/connectors/issues/133)) ([1ac8cd8](https://github.com/Unique-AG/connectors/commit/1ac8cd884341a5e0869fd933dbc5a8f60205f8d3))


### Bug Fixes

* **sharepoint-connector:** do not hairpin for upload when calling in cluster ([#134](https://github.com/Unique-AG/connectors/issues/134)) ([d261e02](https://github.com/Unique-AG/connectors/commit/d261e02ef213717b20ab6d1ab0a9ef266e35c67a))

## [2.0.0-alpha.17](https://github.com/Unique-AG/connectors/compare/sharepoint-connector@v2.0.0-alpha.16...sharepoint-connector@v2.0.0-alpha.17) (2025-11-25)


### Features

* **sharepoint-connector:** removed logs without a level from the ms graph client sdk ([#131](https://github.com/Unique-AG/connectors/issues/131)) ([8c3a792](https://github.com/Unique-AG/connectors/commit/8c3a7926d7b3783a6605fbdca2b342108d9c3230))


### Bug Fixes

* **sharepoint-connector:** add regression test for multiple siteids ([#128](https://github.com/Unique-AG/connectors/issues/128)) ([55ef4f1](https://github.com/Unique-AG/connectors/commit/55ef4f1ceeb5829fa529cea92c86ee05243ef892))
* **sharepoint-connector:** post-testing fixes and improvements ([#129](https://github.com/Unique-AG/connectors/issues/129)) ([5969b9f](https://github.com/Unique-AG/connectors/commit/5969b9fabdb09770ca47591da23082392b8d33ab))
* **sharepoint-connector:** Remove permissions related hacks ([#126](https://github.com/Unique-AG/connectors/issues/126)) ([0b28859](https://github.com/Unique-AG/connectors/commit/0b28859cd227840f0847682f72230f95ebb77556))

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
