# Changelog

## [0.3.4](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.3.3...teams-mcp@0.3.4) (2026-07-16)


### Features

* **teams-mcp:** ensure service-user permissions on root scope at startup ([#693](https://github.com/Unique-AG/connectors/issues/693)) ([d397eb4](https://github.com/Unique-AG/connectors/commit/d397eb4e77668a18a46950f997d50fa2c0b3091d))
* **teams-mcp:** remove list_meetings and find_transcripts tools ([#692](https://github.com/Unique-AG/connectors/issues/692)) ([5523379](https://github.com/Unique-AG/connectors/commit/5523379abd4c96e124b17d245f307bed97a1e240))


### Bug Fixes

* **teams-mcp:** tolerate null contentCorrelationId and optional organizer tenantId ([#689](https://github.com/Unique-AG/connectors/issues/689)) ([6d12464](https://github.com/Unique-AG/connectors/commit/6d12464c18fe1c1e1ff18036d9cdea4bbaffd6b6))

## [0.3.3](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.3.2...teams-mcp@0.3.3) (2026-07-09)


### Bug Fixes

* **teams-mcp:** only send OData params Graph supports on chat/channel message endpoints [UN-22733] ([#685](https://github.com/Unique-AG/connectors/issues/685)) ([82e333f](https://github.com/Unique-AG/connectors/commit/82e333f24c541bb83807383f7341059a66f98319))

## [0.3.2](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.3.1...teams-mcp@0.3.2) (2026-07-09)


### Bug Fixes

* **teams-mcp:** chat message rendering + chatId description hardening [UN-22733] ([#683](https://github.com/Unique-AG/connectors/issues/683)) ([3377b8c](https://github.com/Unique-AG/connectors/commit/3377b8c3538f3a8f2cd96f11d5d46307a545295b))

## [0.3.1](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.3.0...teams-mcp@0.3.1) (2026-07-07)


### Bug Fixes

* **teams-mcp:** replace favicon set with custom MS Teams logo ([#681](https://github.com/Unique-AG/connectors/issues/681)) ([c1519ae](https://github.com/Unique-AG/connectors/commit/c1519ae313262ddf49bf55487a3c166400a15569))

## [0.3.0](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.2.23...teams-mcp@0.3.0) (2026-07-07)


### ⚠ BREAKING CHANGES

* **confluence-connector,sharepoint-connector,teams-mcp,outlook-semantic-mcp:** The `values.yaml` structure for all four charts was reorganised in #658. The `connector:` and `server:` alias namespaces were removed; all values now live at the top level under the five-domain layout. Existing `values.yaml` overrides must be updated accordingly.

### Features

* **confluence-connector,sharepoint-connector,teams-mcp,outlook-semantic-mcp,ci,scripts:** migrate helm charts to base library ([#658](https://github.com/Unique-AG/connectors/issues/658)) ([2ff907f](https://github.com/Unique-AG/connectors/commit/2ff907fb3b6793622fe236f33caf37874651e4ec))
* **confluence-connector,sharepoint-connector,teams-mcp,outlook-semantic-mcp:** mark helm chart base-library migration as breaking change ([#680](https://github.com/Unique-AG/connectors/issues/680)) ([4343627](https://github.com/Unique-AG/connectors/commit/4343627911371db4107376a9c2a0fbd2d57aaf1b))

## [0.2.23](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.2.22...teams-mcp@0.2.23) (2026-07-01)


### Features

* **teams-mcp,deps:** add GET /health operational-status endpoint (UN-19379) ([#676](https://github.com/Unique-AG/connectors/issues/676)) ([45f4e05](https://github.com/Unique-AG/connectors/commit/45f4e05b66c0c892c5e0fba58c23c6bdb642ceb1))
* **teams-mcp:** auto-start ingestion at login (UN-22169) ([#659](https://github.com/Unique-AG/connectors/issues/659)) ([2ca39fc](https://github.com/Unique-AG/connectors/commit/2ca39fc1547ebba2e438641a452d41b38a2a5397))


### Bug Fixes

* **teams-mcp:** attribute upstream Microsoft/network failures to the consumer ([#663](https://github.com/Unique-AG/connectors/issues/663)) ([d211763](https://github.com/Unique-AG/connectors/commit/d211763b2e06a54f7b48e270c73fd0594bb72a6f))

## [0.2.22](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.2.21...teams-mcp@0.2.22) (2026-06-23)


### Features

* **teams-mcp:** id-only chat/channel targeting ([#656](https://github.com/Unique-AG/connectors/issues/656)) ([d1033b8](https://github.com/Unique-AG/connectors/commit/d1033b8e0ca45502eab6d7da0e06d2940185381c))

## [0.2.21](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.2.20...teams-mcp@0.2.21) (2026-06-22)


### Features

* **teams-mcp:** interactive disambiguation + richer list metadata ([#653](https://github.com/Unique-AG/connectors/issues/653)) ([30e7400](https://github.com/Unique-AG/connectors/commit/30e7400d0c220c5ebb4de9ea79ac34dce8d2ca86))

## [0.2.20](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.2.19...teams-mcp@0.2.20) (2026-06-20)


### Features

* **teams-mcp,deps:** add Teams chat & channel messaging tools (8 tools) ([#344](https://github.com/Unique-AG/connectors/issues/344)) ([116780a](https://github.com/Unique-AG/connectors/commit/116780a12e00c6dd484c1af359cb927337284252))

## [0.2.19](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.2.18...teams-mcp@0.2.19) (2026-06-18)


### Features

* **teams-mcp:** add subject and meeting_id to ingested artifact metadata ([#638](https://github.com/Unique-AG/connectors/issues/638)) ([d6054a6](https://github.com/Unique-AG/connectors/commit/d6054a6739f2814d734b59d83375aa149b0a78aa))
* **teams-mcp:** folder-per-meeting ingestion + folder ACL + source-based discovery ([#640](https://github.com/Unique-AG/connectors/issues/640)) ([64238f0](https://github.com/Unique-AG/connectors/commit/64238f0b32f411e1fe56da0d3c18f0a053327b38))


### Bug Fixes

* **deps:** resolve dependency vulnerabilities ([#637](https://github.com/Unique-AG/connectors/issues/637)) ([a91efe6](https://github.com/Unique-AG/connectors/commit/a91efe65c7595ab0ab75523edac3481499ed6866))


### Reverts

* **teams-mcp:** restore nested + locked meeting folder ingestion ([#646](https://github.com/Unique-AG/connectors/issues/646)) ([4d9805b](https://github.com/Unique-AG/connectors/commit/4d9805ba7f0bfcf2b3fa0f237d6e82b654f29616))

## [0.2.18](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.2.17...teams-mcp@0.2.18) (2026-06-08)


### Bug Fixes

* **teams-mcp:** skip inaccessible recordings without dangling KB records ([#623](https://github.com/Unique-AG/connectors/issues/623)) ([6be77e3](https://github.com/Unique-AG/connectors/commit/6be77e31e547dc87dc2c36968e030cf6da55128d))

## [0.2.17](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.2.16...teams-mcp@0.2.17) (2026-06-08)


### Bug Fixes

* **teams-mcp:** stream content uploads via disk-spool ([#619](https://github.com/Unique-AG/connectors/issues/619)) ([99ed6cd](https://github.com/Unique-AG/connectors/commit/99ed6cd17221c8b7916624168dbaf3dda932e7f1))

## [0.2.16](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.2.15...teams-mcp@0.2.16) (2026-06-05)


### Bug Fixes

* **teams-mcp:** send Content-Length on storage upload to avoid chunked rejection ([#614](https://github.com/Unique-AG/connectors/issues/614)) ([b6ce58b](https://github.com/Unique-AG/connectors/commit/b6ce58b1c7c4c61670b9efca3a381d5e5c3b8943))

## [0.2.15](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.2.14...teams-mcp@0.2.15) (2026-06-05)


### Bug Fixes

* **teams-mcp:** route internal content upload through ingestion service ([#608](https://github.com/Unique-AG/connectors/issues/608)) ([f9db6d2](https://github.com/Unique-AG/connectors/commit/f9db6d23fd70458fab6af45501e1853baa0e675d))

## [0.2.14](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.2.13...teams-mcp@0.2.14) (2026-06-04)


### Bug Fixes

* **teams-mcp:** parse folder update response as folder-info ([#602](https://github.com/Unique-AG/connectors/issues/602)) ([7b96320](https://github.com/Unique-AG/connectors/commit/7b96320b56274d9e73f1a8c317e5295985e437dd))

## [0.2.13](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.2.12...teams-mcp@0.2.13) (2026-06-03)


### Features

* **teams-mcp:** add ingest_meeting tool for on-demand transcript ingestion ([#594](https://github.com/Unique-AG/connectors/issues/594)) ([105e01c](https://github.com/Unique-AG/connectors/commit/105e01c9e850eb3bc0cb4a1e8d8ae45ab59bca84))
* **teams-mcp:** tag Teams content with shared source + lock scopes via externalId [UN-20155] ([#592](https://github.com/Unique-AG/connectors/issues/592)) ([1cc0cda](https://github.com/Unique-AG/connectors/commit/1cc0cda55700a9b6dae1a9eb4a370efc5b11cb9b))

## [0.2.12](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.2.11...teams-mcp@0.2.12) (2026-06-01)


### Features

* **charts,outlook-semantic-mcp,sharepoint-connector,teams-mcp:** add admin consent redirect uris ([#577](https://github.com/Unique-AG/connectors/issues/577)) ([3e36a6d](https://github.com/Unique-AG/connectors/commit/3e36a6deea5e620b6e5316a7f3df0dd4fd5c74b3))


### Bug Fixes

* **teams-mcp:** remove inline networkPolicy chart defaults ([#581](https://github.com/Unique-AG/connectors/issues/581)) ([fe8c617](https://github.com/Unique-AG/connectors/commit/fe8c6172312c2be603fac26aa73f44dbe23e6140))

## [0.2.11](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.2.10...teams-mcp@0.2.11) (2026-05-18)


### Bug Fixes

* **deps,teams-mcp:** argo sync ([#559](https://github.com/Unique-AG/connectors/issues/559)) ([c43a883](https://github.com/Unique-AG/connectors/commit/c43a8837f998d05408e872df31e87137b5cc3808))

## [0.2.10](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.2.9...teams-mcp@0.2.10) (2026-05-13)


### Bug Fixes

* **teams-mcp:** restore per-occurrence date folder for transcript ingestion ([#540](https://github.com/Unique-AG/connectors/issues/540)) ([6d4f48d](https://github.com/Unique-AG/connectors/commit/6d4f48d55cb13961215c08f9409560757d9bc719))

## [0.2.9](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.2.8...teams-mcp@0.2.9) (2026-05-06)


### Bug Fixes

* **teams-mcp:** propagate Microsoft invalid_grant as McpError for proper client re-auth signal ([#511](https://github.com/Unique-AG/connectors/issues/511)) ([d3c4cc2](https://github.com/Unique-AG/connectors/commit/d3c4cc283d8f176dfd5f5a2c7a8293307c0e4812))

## [0.2.8](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.2.7...teams-mcp@0.2.8) (2026-05-05)


### Features

* **teams-mcp:** add start_datetime and end_datetime to meeting metadata (UN-20156) ([#507](https://github.com/Unique-AG/connectors/issues/507)) ([b55038c](https://github.com/Unique-AG/connectors/commit/b55038c72ad659e337b6dc8e381ef269b7333979))


### Bug Fixes

* **deps:** upgrade nestjs-otel to v8 to resolve systeminformation CVEs ([#471](https://github.com/Unique-AG/connectors/issues/471)) ([ec584a9](https://github.com/Unique-AG/connectors/commit/ec584a95427b3a9989387c548d654c8b4fbbd775))
* **teams-mcp:** set scoreThreshold 0 in find_transcripts to stop silent result filtering ([#465](https://github.com/Unique-AG/connectors/issues/465)) ([9d3eb35](https://github.com/Unique-AG/connectors/commit/9d3eb357c6e0bbe2604ad53e3da6ef7d428b639b))

## [0.2.7](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.2.6...teams-mcp@0.2.7) (2026-04-14)


### Features

* **confluence-connector,unique-api,utils,deps:** implement ingestion pipeline ([#305](https://github.com/Unique-AG/connectors/issues/305)) ([7d2c64c](https://github.com/Unique-AG/connectors/commit/7d2c64c1f4248e06a822a7d827715c4ae001eeec))
* **teams-mcp:** organizer metadata, hybrid search, and list_meetings tool ([#456](https://github.com/Unique-AG/connectors/issues/456)) ([aa516fc](https://github.com/Unique-AG/connectors/commit/aa516fc757e841b282ebf80337f482de47828ce7))


### Bug Fixes

* **deps:** enable stripLeadingPaths in SWC builder for all services ([#458](https://github.com/Unique-AG/connectors/issues/458)) ([caa3abc](https://github.com/Unique-AG/connectors/commit/caa3abc26b9aea44dede0ce89101df64b3f97b77))
* **deps:** resolve Dependabot security alerts for multiple transitive dependencies ([#449](https://github.com/Unique-AG/connectors/issues/449)) ([c800b51](https://github.com/Unique-AG/connectors/commit/c800b51439145282cababd491a6fba1a84a748a9))
* **deps:** resolve Dependabot security alerts related to jsonwebtoken, js-yaml and @nestjs/ libraries ([#446](https://github.com/Unique-AG/connectors/issues/446)) ([44835ec](https://github.com/Unique-AG/connectors/commit/44835ec851589e2288fd2e1551ca22edb148190e))
* **teams-mcp:** parse GraphError body from ReadableStream on getStream() failures ([#462](https://github.com/Unique-AG/connectors/issues/462)) ([1579c2c](https://github.com/Unique-AG/connectors/commit/1579c2c29b3d4913512f53c29d46a98c6c356ed5))
* **teams-mcp:** pass through Graph API status codes to MCP clients ([#405](https://github.com/Unique-AG/connectors/issues/405)) ([36a784b](https://github.com/Unique-AG/connectors/commit/36a784b63c75480a79e44bf183b9f83f08fb826c))

## [0.2.6](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.2.5...teams-mcp@0.2.6) (2026-02-26)


### Features

* **teams-mcp:** add scoped search with cached user identity mapping ([#295](https://github.com/Unique-AG/connectors/issues/295)) ([03d7266](https://github.com/Unique-AG/connectors/commit/03d7266572435866aea708e06b45099f15655315))


### Bug Fixes

* **teams-mcp:** support both tenantId and organizationId in lifecycle notifications ([#301](https://github.com/Unique-AG/connectors/issues/301)) ([7868251](https://github.com/Unique-AG/connectors/commit/786825171e9e8ae4a268bfa8166815549996c005))
* **teams-mcp:** use tenantId directly in lifecycle notification schema ([#290](https://github.com/Unique-AG/connectors/issues/290)) ([4062c72](https://github.com/Unique-AG/connectors/commit/4062c72b4d7827d6ca3e1cc3a7fa6ebc68da4dbe))

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
