# Changelog

## [0.1.2](https://github.com/Unique-AG/connectors/compare/kyckr-mcp@0.1.1...kyckr-mcp@0.1.2) (2026-11-28)


### Features

* **kyckr-mcp:** add mcpConfig.zitadel.clientId to the chart (UN-29516) ([#1892](https://github.com/Unique-AG/connectors/issues/1892)) ([770f565](https://github.com/Unique-AG/connectors/commit/770f565dd75a1f379285a2756e0e57c0e4e65740))
* **kyckr-mcp:** add the Key Vault secrets Terraform module (UN-29516) ([#1915](https://github.com/Unique-AG/connectors/issues/1915)) ([84dfe57](https://github.com/Unique-AG/connectors/commit/84dfe57faa8fe0e223a2593e01c5449361285ba9))
* **kyckr-mcp:** redact the deployment's secrets from every log line ([#1442](https://github.com/Unique-AG/connectors/issues/1442)) ([5b5662c](https://github.com/Unique-AG/connectors/commit/5b5662cbc127a8ad6a37d9dd195fe9e93088beda))
* **main:** replace the NestJS kyckr-mcp with one built on the MCP scaffold (UN-29515) ([#1709](https://github.com/Unique-AG/connectors/issues/1709)) ([70ea7ae](https://github.com/Unique-AG/connectors/commit/70ea7ae3e1c805c879faeadceedfb8cf0bb2483b))


### Bug Fixes

* **instrumentation,kyckr-mcp,temenos-mcp:** redact the API key from OpenTelemetry spans and HTTP metrics ([#1352](https://github.com/Unique-AG/connectors/issues/1352)) ([3b07ea9](https://github.com/Unique-AG/connectors/commit/3b07ea948db1441021f851d45865a0476c8ee8d9))
* **kyckr-mcp,temenos-mcp:** add timeouts, 429 backoff and body size cap to upstream HTTP clients ([#1351](https://github.com/Unique-AG/connectors/issues/1351)) ([5262d69](https://github.com/Unique-AG/connectors/commit/5262d69549fa1a1a364cc532edabfc6c2bca54c2))
* **teams-mcp,outlook-semantic-mcp,kb-mcp,backstop-mcp,with-intelligence-mcp,kyckr-mcp,temenos-mcp:** mark upstream content as untrusted in tool descriptions ([#1355](https://github.com/Unique-AG/connectors/issues/1355)) ([8aeef96](https://github.com/Unique-AG/connectors/commit/8aeef9675771f2f121e2dafae722d8bfdc4b294b))


### Dependencies

* **deps:** bump argcomplete from 3.7.2 to 3.8.0 ([#1900](https://github.com/Unique-AG/connectors/issues/1900)) ([d61b0c4](https://github.com/Unique-AG/connectors/commit/d61b0c4fbb073e9f77cde8728a27de700b20f3c9))
* **deps:** bump authlib from 1.9.7 to 1.9.10 ([#1901](https://github.com/Unique-AG/connectors/issues/1901)) ([9a0f122](https://github.com/Unique-AG/connectors/commit/9a0f122cfc6aa301d86e61284149427d3ece1463))
* **deps:** bump certifi from 2026.10.23 to 2026.11.20 ([#1895](https://github.com/Unique-AG/connectors/issues/1895)) ([b7d827d](https://github.com/Unique-AG/connectors/commit/b7d827d8d5a014dc20c8841a7dd5cd4c2c55f5de))
* **deps:** bump cyclopts from 5.5.1 to 5.5.2 ([#1902](https://github.com/Unique-AG/connectors/issues/1902)) ([6b9b451](https://github.com/Unique-AG/connectors/commit/6b9b45197066b6b7e436e4be7a1a15dc007121b2))
* **deps:** bump exceptiongroup from 1.3.1 to 1.3.2 ([#1903](https://github.com/Unique-AG/connectors/issues/1903)) ([f869dbc](https://github.com/Unique-AG/connectors/commit/f869dbc74657054737196077cfc2f54309a64185))
* **deps:** bump filelock from 4.2.10 to 4.3.0 ([#1904](https://github.com/Unique-AG/connectors/issues/1904)) ([4a5e291](https://github.com/Unique-AG/connectors/commit/4a5e291583f7760f9f6f8e9f103a21000ad52888))
* **deps:** bump import-linter from 2.16 to 2.17 ([#1905](https://github.com/Unique-AG/connectors/issues/1905)) ([70b419a](https://github.com/Unique-AG/connectors/commit/70b419a78918bd39957bae15139a1b6860ff42bf))
* **deps:** bump node from 26.12.1-trixie@a98e6fda54fd to 26.13.0-trixie@6d2c7d5d074b ([#1430](https://github.com/Unique-AG/connectors/issues/1430)) ([72e4fc2](https://github.com/Unique-AG/connectors/commit/72e4fc26b28c855225a14e83c57ce575f8d77ff4))
* **deps:** bump node from 26.13.0-trixie@6d2c7d5d074b to 26.13.0-trixie@438603bbb5cd ([#1580](https://github.com/Unique-AG/connectors/issues/1580)) ([2e26f6b](https://github.com/Unique-AG/connectors/commit/2e26f6b75e6692aa38e4f7e423d758547c87c72b))
* **deps:** bump node to 26.13.1 security release ([#1642](https://github.com/Unique-AG/connectors/issues/1642)) ([407761d](https://github.com/Unique-AG/connectors/commit/407761d268c76b3a57f755f245fd7e08bb674278))
* **deps:** bump platformdirs from 4.14.5 to 4.14.8 ([#1906](https://github.com/Unique-AG/connectors/issues/1906)) ([b6c6a1e](https://github.com/Unique-AG/connectors/commit/b6c6a1eb694b5cacbb3dcf529d9700eea5b8ea5f))
* **deps:** bump pytest-asyncio from 1.4.1.post1 to 1.5.0 ([#1896](https://github.com/Unique-AG/connectors/issues/1896)) ([eff732b](https://github.com/Unique-AG/connectors/commit/eff732bfc6877a0506be086849bcc69c9edcedba))
* **deps:** bump python-multipart from 0.0.33 to 0.0.34 ([#1907](https://github.com/Unique-AG/connectors/issues/1907)) ([6a2df8d](https://github.com/Unique-AG/connectors/commit/6a2df8d0f1b75f8e052b9597e1e2d0b2527242a3))
* **deps:** bump pyyaml from 6.0.3 to 6.0.4 ([#1897](https://github.com/Unique-AG/connectors/issues/1897)) ([69f9b00](https://github.com/Unique-AG/connectors/commit/69f9b004e37a2bedfca0270c27957ca07c11b297))
* **deps:** bump regex from 2026.11.15 to 2026.11.19 ([#1908](https://github.com/Unique-AG/connectors/issues/1908)) ([8fba6ea](https://github.com/Unique-AG/connectors/commit/8fba6ea62cee7f4e6be785d7a5e55d6bc3137dd5))
* **deps:** bump sse-starlette from 3.7.0 to 3.7.1 ([#1909](https://github.com/Unique-AG/connectors/issues/1909)) ([a938777](https://github.com/Unique-AG/connectors/commit/a9387775399515a9c334552a70eefddd639f97cd))
* **deps:** bump typeguard from 4.6.0 to 4.6.1 ([#1910](https://github.com/Unique-AG/connectors/issues/1910)) ([f1fb71a](https://github.com/Unique-AG/connectors/commit/f1fb71a5a5b2683d7820eee09eb72d0fabcc4414))
* **deps:** bump uncalled-for from 0.6.1 to 0.6.2 ([#1911](https://github.com/Unique-AG/connectors/issues/1911)) ([d2db69d](https://github.com/Unique-AG/connectors/commit/d2db69db75e0fc78fa3985f63de7d953fba34bfa))
* **main:** bump @proventuslabs/nestjs-zod from 2.0.0 to 2.2.0 ([#1390](https://github.com/Unique-AG/connectors/issues/1390)) ([023787c](https://github.com/Unique-AG/connectors/commit/023787cc8c364d1c192d06192a1541940fa77b9e))
