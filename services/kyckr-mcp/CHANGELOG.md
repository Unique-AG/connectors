# Changelog

## [0.1.1-alpha.1](https://github.com/Unique-AG/connectors/compare/kyckr-mcp@0.1.1-alpha...kyckr-mcp@0.1.1-alpha.1) (2026-11-13)


### Features

* **kyckr-mcp:** redact the deployment's secrets from every log line ([#1442](https://github.com/Unique-AG/connectors/issues/1442)) ([5b5662c](https://github.com/Unique-AG/connectors/commit/5b5662cbc127a8ad6a37d9dd195fe9e93088beda))


### Bug Fixes

* **confluence-connector,kyckr-mcp,outlook-semantic-mcp,sharepoint-connector,teams-mcp,temenos-mcp:** bump node to 26.12.1 security release ([#1269](https://github.com/Unique-AG/connectors/issues/1269)) ([c57480f](https://github.com/Unique-AG/connectors/commit/c57480fbd576cbae8a53d35975e01db345f65c7b))
* **instrumentation,kyckr-mcp,temenos-mcp:** redact the API key from OpenTelemetry spans and HTTP metrics ([#1352](https://github.com/Unique-AG/connectors/issues/1352)) ([3b07ea9](https://github.com/Unique-AG/connectors/commit/3b07ea948db1441021f851d45865a0476c8ee8d9))
* **kyckr-mcp,temenos-mcp:** add timeouts, 429 backoff and body size cap to upstream HTTP clients ([#1351](https://github.com/Unique-AG/connectors/issues/1351)) ([5262d69](https://github.com/Unique-AG/connectors/commit/5262d69549fa1a1a364cc532edabfc6c2bca54c2))
* **teams-mcp,outlook-semantic-mcp,kb-mcp,backstop-mcp,with-intelligence-mcp,kyckr-mcp,temenos-mcp:** mark upstream content as untrusted in tool descriptions ([#1355](https://github.com/Unique-AG/connectors/issues/1355)) ([8aeef96](https://github.com/Unique-AG/connectors/commit/8aeef9675771f2f121e2dafae722d8bfdc4b294b))


### Dependencies

* bump node in /services/*/deploy ([#1142](https://github.com/Unique-AG/connectors/issues/1142)) ([336dd69](https://github.com/Unique-AG/connectors/commit/336dd694053576d07366c6f0adbf30f45ed95988))
* bump node in /services/*/deploy ([#1232](https://github.com/Unique-AG/connectors/issues/1232)) ([fd0e934](https://github.com/Unique-AG/connectors/commit/fd0e934ec3ad1e9d9cb38a2e5003d6bfae46a4b2))
* **deps:** bump node from 26.12.1-trixie@a98e6fda54fd to 26.13.0-trixie@6d2c7d5d074b ([#1430](https://github.com/Unique-AG/connectors/issues/1430)) ([72e4fc2](https://github.com/Unique-AG/connectors/commit/72e4fc26b28c855225a14e83c57ce575f8d77ff4))
* **deps:** bump node from 26.13.0-trixie@6d2c7d5d074b to 26.13.0-trixie@438603bbb5cd ([#1580](https://github.com/Unique-AG/connectors/issues/1580)) ([2e26f6b](https://github.com/Unique-AG/connectors/commit/2e26f6b75e6692aa38e4f7e423d758547c87c72b))
* **deps:** bump node to 26.13.1 security release ([#1642](https://github.com/Unique-AG/connectors/issues/1642)) ([407761d](https://github.com/Unique-AG/connectors/commit/407761d268c76b3a57f755f245fd7e08bb674278))
* **main:** bump @proventuslabs/nestjs-zod from 2.0.0 to 2.2.0 ([#1390](https://github.com/Unique-AG/connectors/issues/1390)) ([023787c](https://github.com/Unique-AG/connectors/commit/023787cc8c364d1c192d06192a1541940fa77b9e))

## [0.1.1-alpha](https://github.com/Unique-AG/connectors/compare/kyckr-mcp@0.1.0...kyckr-mcp@0.1.1-alpha) (2026-09-21)


### Dependencies

* bump node from 26.7.0-trixie-slim to 26.8.1-trixie-slim in /services/kyckr-mcp/deploy ([#922](https://github.com/Unique-AG/connectors/issues/922)) ([437546a](https://github.com/Unique-AG/connectors/commit/437546a0f53688b49cc9df15971c762885e3b33d))
* bump node in /services/*/deploy ([#1061](https://github.com/Unique-AG/connectors/issues/1061)) ([900cf1d](https://github.com/Unique-AG/connectors/commit/900cf1da2c09c5ccf86724b16472405d7c4e8c11))
* bump node in /services/confluence-connector/deploy ([#996](https://github.com/Unique-AG/connectors/issues/996)) ([0b051f4](https://github.com/Unique-AG/connectors/commit/0b051f4a54096b2b91e9e5f2bea8e41d52444855))
* **deps,ci,main:** update 67 pnpm dependencies within their current majors ([#862](https://github.com/Unique-AG/connectors/issues/862)) ([bef205f](https://github.com/Unique-AG/connectors/commit/bef205f33962020c7a94879c98858fe847aa53a6))
* **deps:** align Node engines, CI, and types with Docker Node 26 ([#849](https://github.com/Unique-AG/connectors/issues/849)) ([0b053a9](https://github.com/Unique-AG/connectors/commit/0b053a99f4540463d5385665c4fe1320ca3ff647))
* **deps:** bump the service-base-images group across 8 directories with 3 updates ([#788](https://github.com/Unique-AG/connectors/issues/788)) ([7187ed7](https://github.com/Unique-AG/connectors/commit/7187ed758f2a1d4114a01e8dd2e414936ea3b5e4))
* put every dependency in the right group, name what was missing, and hold shared versions in the pnpm catalog ([#958](https://github.com/Unique-AG/connectors/issues/958)) ([794092f](https://github.com/Unique-AG/connectors/commit/794092faa348052eddf2be580ed61fc771684b6f))
* remove pnpm from the Node runtime images ([#1035](https://github.com/Unique-AG/connectors/issues/1035)) ([5ad580a](https://github.com/Unique-AG/connectors/commit/5ad580abb79f72f60d4e68a461c301c816692fcd))
* stop shipping dev dependencies in the service images ([#978](https://github.com/Unique-AG/connectors/issues/978)) ([29c1613](https://github.com/Unique-AG/connectors/commit/29c1613b89b5dd0edb0cd2dd92bdf921bf26c18a))
* **teams-mcp,outlook-semantic-mcp,sharepoint-connector,confluence-connector,kyckr-mcp,temenos-mcp,ir-demo-mcp,ci,deps:** dockerfiles and dependabot harmonized and updated ([#720](https://github.com/Unique-AG/connectors/issues/720)) ([a079984](https://github.com/Unique-AG/connectors/commit/a079984c612f5dc24e5bf1bdf61fe553015a6597))
* upgrade vitest to 5.0.0 and migrate the mocks it breaks ([#970](https://github.com/Unique-AG/connectors/issues/970)) ([9474b72](https://github.com/Unique-AG/connectors/commit/9474b72bc43b99f6e2bf996794145c0aad84f519))

## 0.1.0 (2026-07-10)


### ⚠ BREAKING CHANGES

* **sharepoint-connector,outlook-mcp,factset-mcp:** all git tags no longer include the version 'v'. In a future version, all releases will also not include the v anymore.

### Features

* **kyckr-mcp,ci,deps,main:** add kyckr-mcp service ([#531](https://github.com/Unique-AG/connectors/issues/531)) ([6a4d234](https://github.com/Unique-AG/connectors/commit/6a4d23406d975811fccb6b19cf4300b197506f74))
* **kyckr-mcp:** download document as json format ([#546](https://github.com/Unique-AG/connectors/issues/546)) ([3a9ad40](https://github.com/Unique-AG/connectors/commit/3a9ad408020bbd77b517d13918a5f4fd2e5a647a))
* **sharepoint-connector,outlook-mcp,factset-mcp:** remove v in tags ([#168](https://github.com/Unique-AG/connectors/issues/168)) ([2f56700](https://github.com/Unique-AG/connectors/commit/2f5670000c968d8bf0e0051eeb47766f586c84cc))


### Bug Fixes

* **deps:** address pnpm audit vulnerabilities ([#650](https://github.com/Unique-AG/connectors/issues/650)) ([f7cbc71](https://github.com/Unique-AG/connectors/commit/f7cbc71e8ada8778548d8f1d064753ca5355dc25))

## Changelog
