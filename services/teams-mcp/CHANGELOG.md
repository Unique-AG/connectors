# Changelog

## [0.5.1](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.5.0...teams-mcp@0.5.1) (2026-11-12)


### Dependencies

* **deps:** bump azurerm from 5.12.0 to 5.13.0 ([#1572](https://github.com/Unique-AG/connectors/issues/1572)) ([697230b](https://github.com/Unique-AG/connectors/commit/697230b664bd3098f2a4902e2ae66c5cc028c478))
* **deps:** bump node from 26.13.0-trixie@6d2c7d5d074b to 26.13.0-trixie@438603bbb5cd ([#1580](https://github.com/Unique-AG/connectors/issues/1580)) ([2e26f6b](https://github.com/Unique-AG/connectors/commit/2e26f6b75e6692aa38e4f7e423d758547c87c72b))
* **deps:** bump node to 26.13.1 security release ([#1642](https://github.com/Unique-AG/connectors/issues/1642)) ([407761d](https://github.com/Unique-AG/connectors/commit/407761d268c76b3a57f755f245fd7e08bb674278))
* **main:** bump @proventuslabs/nestjs-zod from 2.0.0 to 2.2.0 ([#1390](https://github.com/Unique-AG/connectors/issues/1390)) ([023787c](https://github.com/Unique-AG/connectors/commit/023787cc8c364d1c192d06192a1541940fa77b9e))

## [0.5.0](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.4.12...teams-mcp@0.5.0) (2026-11-10)


### ⚠ BREAKING CHANGES

* **mcp-oauth,teams-mcp,outlook-semantic-mcp,office-365-mcp:** reject sign-ins from Entra tenants not on the allowlist ([#1357](https://github.com/Unique-AG/connectors/issues/1357))

### Features

* **backstop-mcp,kb-mcp,office-365-mcp,outlook-semantic-mcp,teams-mcp,with-intelligence-mcp:** advertise the new server icon in serverInfo ([#1377](https://github.com/Unique-AG/connectors/issues/1377)) ([19e8a00](https://github.com/Unique-AG/connectors/commit/19e8a009ff76826a0d606c241197cea432cfcebe))
* **ci,main:** gate releases, scan images nightly, and update dependencies nightly ([#1305](https://github.com/Unique-AG/connectors/issues/1305)) ([b3b274c](https://github.com/Unique-AG/connectors/commit/b3b274cf0ab3cecc3a1dece3eff5c116d24d9418))
* **mcp-oauth,teams-mcp,outlook-semantic-mcp:** ask the user to approve each MCP client before signing in with Entra ([#1337](https://github.com/Unique-AG/connectors/issues/1337)) ([1f64988](https://github.com/Unique-AG/connectors/commit/1f649887cef2388a2d34d1499ac43c60bd1f7ff5))
* **mcp-server-module,mcp-observability:** rate-limit MCP tool calls per user ([#1358](https://github.com/Unique-AG/connectors/issues/1358)) ([bbe4bc0](https://github.com/Unique-AG/connectors/commit/bbe4bc07bde6b67cecee762e25a16cfeac6cc67a))
* **outlook-semantic-mcp,teams-mcp:** advertise the server icon in serverInfo ([#1255](https://github.com/Unique-AG/connectors/issues/1255)) ([a7b78ab](https://github.com/Unique-AG/connectors/commit/a7b78ab5163598a25dd17d7ec443d2de79cc4fbb))
* **teams-mcp,outlook-semantic-mcp,recordings-and-transcripts:** redirect tenant admins to Entra admin consent at /admin/consent ([#1529](https://github.com/Unique-AG/connectors/issues/1529)) ([9a4e045](https://github.com/Unique-AG/connectors/commit/9a4e04557276de01d761569717dec596b3287071))
* **teams-mcp:** redact the deployment's secrets and each caller's tokens from every log line ([#1443](https://github.com/Unique-AG/connectors/issues/1443)) ([86fd8ee](https://github.com/Unique-AG/connectors/commit/86fd8ee21402108fad98b1cf2c681cc757d1093f))


### Bug Fixes

* **architecture-demo-mcp,backstop-mcp,confluence-connector,hello-mcp,kb-mcp,main,mcp-scaffold,office-365-mcp,outlook-semantic-mcp,sharepoint-connector,teams-mcp,with-intelligence-mcp:** run migrations as argo cd sync hooks after the database ([#1360](https://github.com/Unique-AG/connectors/issues/1360)) ([5264f9f](https://github.com/Unique-AG/connectors/commit/5264f9f14505bbc57d01fe676946daaf63e261f3))
* **architecture-demo-mcp,backstop-mcp,confluence-connector,hello-mcp,kb-mcp,office-365-mcp,outlook-semantic-mcp,sharepoint-connector,teams-mcp,with-intelligence-mcp:** bump base chart for network policy sync-wave ordering ([#1307](https://github.com/Unique-AG/connectors/issues/1307)) ([8e9eba5](https://github.com/Unique-AG/connectors/commit/8e9eba588c9052ef87a356a0bd9c575170848ca2))
* deny egress to RFC1918 and link-local ranges in every MCP chart ([#1353](https://github.com/Unique-AG/connectors/issues/1353)) ([5949e66](https://github.com/Unique-AG/connectors/commit/5949e6698615dfd7de48116cd09c0550467485f1))
* **mcp-oauth,teams-mcp,outlook-semantic-mcp,deps:** revoke the token family when a refresh token is replayed ([#1336](https://github.com/Unique-AG/connectors/issues/1336)) ([e2fd728](https://github.com/Unique-AG/connectors/commit/e2fd728fa81516a64a6235621221a44413440147))
* **mcp-oauth,teams-mcp,outlook-semantic-mcp,office-365-mcp:** reject sign-ins from Entra tenants not on the allowlist ([#1357](https://github.com/Unique-AG/connectors/issues/1357)) ([4cc5936](https://github.com/Unique-AG/connectors/commit/4cc5936fda54b507ab3183ef0f2c7e6dec109abc))
* **mcp-oauth,teams-mcp,outlook-semantic-mcp:** make the throttler limit per real client IP and register the auth throttler ([#1350](https://github.com/Unique-AG/connectors/issues/1350)) ([aeab994](https://github.com/Unique-AG/connectors/commit/aeab9947cfbf375af18eb4e957e323dedc9bc50b))
* **mcp-oauth,teams-mcp,outlook-semantic-mcp:** store HMAC-SHA256 hashes of MCP tokens instead of plaintext ([#1356](https://github.com/Unique-AG/connectors/issues/1356)) ([a85577d](https://github.com/Unique-AG/connectors/commit/a85577d02e573c03fc38ea71d49d546cce925c9f))
* **teams-mcp,deps:** hide internal ids from users and name chats in list and search results ([#1576](https://github.com/Unique-AG/connectors/issues/1576)) ([b58baa2](https://github.com/Unique-AG/connectors/commit/b58baa2580efef61d125260b726f6b1f9e3890ee))
* **teams-mcp,outlook-semantic-mcp,kb-mcp,backstop-mcp,with-intelligence-mcp,kyckr-mcp,temenos-mcp:** mark upstream content as untrusted in tool descriptions ([#1355](https://github.com/Unique-AG/connectors/issues/1355)) ([8aeef96](https://github.com/Unique-AG/connectors/commit/8aeef9675771f2f121e2dafae722d8bfdc4b294b))
* **teams-mcp,outlook-semantic-mcp:** disable world ingress on ephemeral ports ([#1343](https://github.com/Unique-AG/connectors/issues/1343)) ([4963d0c](https://github.com/Unique-AG/connectors/commit/4963d0cdf39336bfb7e3bab78ae78842f5a233f5))


### Dependencies

* **deps:** bump azurerm from 5.11.0 to 5.12.0 ([#1395](https://github.com/Unique-AG/connectors/issues/1395)) ([582a096](https://github.com/Unique-AG/connectors/commit/582a09693c5656b9b016ea8e42a1317f0fd090de))
* **deps:** bump node from 26.12.1-trixie@a98e6fda54fd to 26.13.0-trixie@6d2c7d5d074b ([#1430](https://github.com/Unique-AG/connectors/issues/1430)) ([72e4fc2](https://github.com/Unique-AG/connectors/commit/72e4fc26b28c855225a14e83c57ce575f8d77ff4))

## [0.4.12](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.4.11...teams-mcp@0.4.12) (2026-10-23)


### Bug Fixes

* **confluence-connector,kyckr-mcp,outlook-semantic-mcp,sharepoint-connector,teams-mcp,temenos-mcp:** bump node to 26.12.1 security release ([#1269](https://github.com/Unique-AG/connectors/issues/1269)) ([c57480f](https://github.com/Unique-AG/connectors/commit/c57480fbd576cbae8a53d35975e01db345f65c7b))
* **mcp-server-module,outlook-semantic-mcp,teams-mcp,deps:** close idle MCP sessions and fix token cache TTL units ([#1169](https://github.com/Unique-AG/connectors/issues/1169)) ([c9a4289](https://github.com/Unique-AG/connectors/commit/c9a4289d9b4b5357bc60b8f54e7e09760074a910))


### Dependencies

* bump node in /services/*/deploy ([#1142](https://github.com/Unique-AG/connectors/issues/1142)) ([336dd69](https://github.com/Unique-AG/connectors/commit/336dd694053576d07366c6f0adbf30f45ed95988))
* bump node in /services/*/deploy ([#1232](https://github.com/Unique-AG/connectors/issues/1232)) ([fd0e934](https://github.com/Unique-AG/connectors/commit/fd0e934ec3ad1e9d9cb38a2e5003d6bfae46a4b2))

## [0.4.11](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.4.10...teams-mcp@0.4.11) (2026-10-07)


### Bug Fixes

* **sharepoint-connector,office-365-mcp,outlook-semantic-mcp,teams-mcp:** stop managing shared Microsoft service principals as destroyable resources ([#1097](https://github.com/Unique-AG/connectors/issues/1097)) ([e8cdadd](https://github.com/Unique-AG/connectors/commit/e8cdaddc16dfd1352797c8b450e8cd244abb0445))
* **teams-mcp,outlook-semantic-mcp:** accept a null latestSupportedTlsVersion from Graph ([#1170](https://github.com/Unique-AG/connectors/issues/1170)) ([ad519eb](https://github.com/Unique-AG/connectors/commit/ad519eb44ce76f3ddc7dc8d592dcd56b939fa472))

## [0.4.10](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.4.9...teams-mcp@0.4.10) (2026-09-21)


### Dependencies

* bump node in /services/*/deploy ([#1061](https://github.com/Unique-AG/connectors/issues/1061)) ([900cf1d](https://github.com/Unique-AG/connectors/commit/900cf1da2c09c5ccf86724b16472405d7c4e8c11))

## [0.4.9](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.4.8...teams-mcp@0.4.9) (2026-09-17)


### Dependencies

* bump node in /services/confluence-connector/deploy ([#996](https://github.com/Unique-AG/connectors/issues/996)) ([0b051f4](https://github.com/Unique-AG/connectors/commit/0b051f4a54096b2b91e9e5f2bea8e41d52444855))
* **outlook-semantic-mcp,teams-mcp:** run migrations without pnpm ([#1034](https://github.com/Unique-AG/connectors/issues/1034)) ([5c95c51](https://github.com/Unique-AG/connectors/commit/5c95c515336437d4e7da95cdb4a1fe927f6e499e))
* remove pnpm from the Node runtime images ([#1035](https://github.com/Unique-AG/connectors/issues/1035)) ([5ad580a](https://github.com/Unique-AG/connectors/commit/5ad580abb79f72f60d4e68a461c301c816692fcd))

## [0.4.8](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.4.7...teams-mcp@0.4.8) (2026-09-10)


### Bug Fixes

* **mcp-oauth,outlook-semantic-mcp,teams-mcp,deps:** re-auth MCP clients on revoked Microsoft grants ([#981](https://github.com/Unique-AG/connectors/issues/981)) ([2c2155b](https://github.com/Unique-AG/connectors/commit/2c2155b643af4b3c5b816c2f33ecf4552798164c))
* **teams-mcp:** send service id header ([#992](https://github.com/Unique-AG/connectors/issues/992)) ([9bd1a3d](https://github.com/Unique-AG/connectors/commit/9bd1a3d33bca81e47890e04460a777821d6bab78))

## [0.4.7](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.4.6...teams-mcp@0.4.7) (2026-09-08)


### Bug Fixes

* **backstop-mcp,confluence-connector,hello-mcp,kb-mcp,office-365-mcp,outlook-semantic-mcp,sharepoint-connector,teams-mcp:** bump base chart dependency to 0.1.0-87990c ([#915](https://github.com/Unique-AG/connectors/issues/915)) ([1bc27a7](https://github.com/Unique-AG/connectors/commit/1bc27a713ab7e2a5bf36671fa1f1f294497c649e))


### Dependencies

* bump @opentelemetry/instrumentation-pg from 0.73.0 to 0.74.0 ([#938](https://github.com/Unique-AG/connectors/issues/938)) ([e68832a](https://github.com/Unique-AG/connectors/commit/e68832adc6426aeb1c40d84464b06f0be84af5ab))
* bump node from 26.7.0-trixie-slim to 26.8.1-trixie-slim in /services/teams-mcp/deploy ([#925](https://github.com/Unique-AG/connectors/issues/925)) ([64c6ad5](https://github.com/Unique-AG/connectors/commit/64c6ad5715ba8c32bc1028700aa549208a956a8c))
* put every dependency in the right group, name what was missing, and hold shared versions in the pnpm catalog ([#958](https://github.com/Unique-AG/connectors/issues/958)) ([794092f](https://github.com/Unique-AG/connectors/commit/794092faa348052eddf2be580ed61fc771684b6f))
* stop shipping dev dependencies in the service images ([#978](https://github.com/Unique-AG/connectors/issues/978)) ([29c1613](https://github.com/Unique-AG/connectors/commit/29c1613b89b5dd0edb0cd2dd92bdf921bf26c18a))
* upgrade biome to 2.5.12 and fix what its new rules flag ([#967](https://github.com/Unique-AG/connectors/issues/967)) ([02bb1dc](https://github.com/Unique-AG/connectors/commit/02bb1dc03307689255d8bbf647fd8b1c611dac67))
* upgrade vitest to 5.0.0 and migrate the mocks it breaks ([#970](https://github.com/Unique-AG/connectors/issues/970)) ([9474b72](https://github.com/Unique-AG/connectors/commit/9474b72bc43b99f6e2bf996794145c0aad84f519))

## [0.4.6](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.4.5...teams-mcp@0.4.6) (2026-09-01)


### Features

* **teams-mcp,recordings-and-transcripts:** allow pinning the Microsoft OAuth tenant ([#879](https://github.com/Unique-AG/connectors/issues/879)) ([8db60ee](https://github.com/Unique-AG/connectors/commit/8db60eee77846871a8e6fd9b41a88567a0632c84))

## [0.4.5](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.4.4...teams-mcp@0.4.5) (2026-08-25)


### Bug Fixes

* **teams-mcp:** fix the four reported message tool bugs and align the tools ([#838](https://github.com/Unique-AG/connectors/issues/838)) ([12c5e34](https://github.com/Unique-AG/connectors/commit/12c5e34a97700679f73b1fb62caa2e9db5dfb9f9))

## [0.4.4](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.4.3...teams-mcp@0.4.4) (2026-08-21)


### Features

* **teams-mcp,recordings-and-transcripts:** drop the unused Calendars.Read scope ([#827](https://github.com/Unique-AG/connectors/issues/827)) ([6a3515a](https://github.com/Unique-AG/connectors/commit/6a3515a45b27ad7039b23bc08e2d0465bb38aff3))
* **teams-mcp:** surface clear error when Graph transcript access is disabled ([#762](https://github.com/Unique-AG/connectors/issues/762)) ([20e787c](https://github.com/Unique-AG/connectors/commit/20e787c9664b66f77ecb1d6cb0bd0bdff5107e1f))


### Bug Fixes

* **confluence-connector,outlook-semantic-mcp,sharepoint-connector,teams-mcp:** allow azurerm v4 or v5 (&gt;= 4, &lt; 6) in remaining modules ([#768](https://github.com/Unique-AG/connectors/issues/768)) ([dcdd34f](https://github.com/Unique-AG/connectors/commit/dcdd34f521aac36ffa7d388c0478b7e4e8237368))
* **teams-mcp:** allow azurerm v4 or v5 (&gt;= 4, &lt; 6) in entra module ([#764](https://github.com/Unique-AG/connectors/issues/764)) ([3b78445](https://github.com/Unique-AG/connectors/commit/3b7844549d2a248f9f1cfe0d97c7c8a48cb96a34))

## [0.4.3](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.4.2...teams-mcp@0.4.3) (2026-08-10)


### Features

* **teams-mcp:** add independent CHAT_INTEGRATION toggle for composable capabilities ([#757](https://github.com/Unique-AG/connectors/issues/757)) ([4d9e5b1](https://github.com/Unique-AG/connectors/commit/4d9e5b12c1464c7f8b7004fc7d2209d4cd26c556))

## [0.4.2](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.4.1...teams-mcp@0.4.2) (2026-07-28)


### Features

* **teams-mcp:** add more logging for transcript ingestion ([#709](https://github.com/Unique-AG/connectors/issues/709)) ([94fe47e](https://github.com/Unique-AG/connectors/commit/94fe47edf5ce001a9cb413e5174309b3847ee96a))

## [0.4.1](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.4.0...teams-mcp@0.4.1) (2026-07-23)


### Features

* **teams-mcp:** request fewer Graph scopes when Unique is disabled ([#703](https://github.com/Unique-AG/connectors/issues/703)) ([b24256f](https://github.com/Unique-AG/connectors/commit/b24256fecd31c23d25866275bab4a2a9e4b1847b))

## [0.4.0](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.3.5...teams-mcp@0.4.0) (2026-07-22)


### ⚠ BREAKING CHANGES

* **teams-mcp:** move autoStartIngestion to unique config ([#699](https://github.com/Unique-AG/connectors/issues/699))

### Features

* **teams-mcp:** move autoStartIngestion to unique config ([#699](https://github.com/Unique-AG/connectors/issues/699)) ([b770528](https://github.com/Unique-AG/connectors/commit/b7705282504b55936f3b9706983ddb16ccae5626))

## [0.3.5](https://github.com/Unique-AG/connectors/compare/teams-mcp@0.3.4...teams-mcp@0.3.5) (2026-07-22)


### Features

* **teams-mcp:** make Unique integration optional via UNIQUE_INTEGRATION ([#697](https://github.com/Unique-AG/connectors/issues/697)) ([9c6dd2d](https://github.com/Unique-AG/connectors/commit/9c6dd2d94a6cc95b0601e8fa11653bc2f467adc6))

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
