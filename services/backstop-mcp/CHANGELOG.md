# Changelog

## [0.0.5](https://github.com/Unique-AG/connectors/compare/backstop-mcp@0.0.4...backstop-mcp@0.0.5) (2026-09-04)


### Bug Fixes

* **backstop-mcp,confluence-connector,hello-mcp,kb-mcp,office-365-mcp,outlook-semantic-mcp,sharepoint-connector,teams-mcp:** bump base chart dependency to 0.1.0-87990c ([#915](https://github.com/Unique-AG/connectors/issues/915)) ([1bc27a7](https://github.com/Unique-AG/connectors/commit/1bc27a713ab7e2a5bf36671fa1f1f294497c649e))


### Dependencies

* **backstop-mcp,hello-mcp,kb-mcp,office-365-mcp:** run the Python services on 3.14 ([#866](https://github.com/Unique-AG/connectors/issues/866)) ([7f2321a](https://github.com/Unique-AG/connectors/commit/7f2321afffb27bcd13e566eea12b0f4c6ceaecc1))
* **backstop-mcp:** build and run on one interpreter ([#899](https://github.com/Unique-AG/connectors/issues/899)) ([9185ed6](https://github.com/Unique-AG/connectors/commit/9185ed6d8469cd977acf62585c669aa0b026cdf0))

## [0.0.4](https://github.com/Unique-AG/connectors/compare/backstop-mcp@0.0.3...backstop-mcp@0.0.4) (2026-08-28)


### Features

* **backstop-mcp,main:** add agent-explore scripts and combined API/docs skill ([#840](https://github.com/Unique-AG/connectors/issues/840)) ([4aafd4a](https://github.com/Unique-AG/connectors/commit/4aafd4adea74454b97b7933a82e1cdb4c761f719))
* **backstop-mcp:** surface custom fields on opportunities and add get_opportunities_by_ids ([#867](https://github.com/Unique-AG/connectors/issues/867)) ([ee83f4c](https://github.com/Unique-AG/connectors/commit/ee83f4c069180fd0d7f54fc868954c12aef85d5c))


### Bug Fixes

* **backstop-mcp:** stop spurious 401s revoking sessions, and bound the ambiguity elicitation ([#852](https://github.com/Unique-AG/connectors/issues/852)) ([0aa0d79](https://github.com/Unique-AG/connectors/commit/0aa0d7905dc5331ebb03927588ecbefa7eb12c49))

## [0.0.3](https://github.com/Unique-AG/connectors/compare/backstop-mcp@0.0.2...backstop-mcp@0.0.3) (2026-08-21)


### Features

* **backstop-mcp,main:** cover remaining CRM question axes with dedicated tools ([#832](https://github.com/Unique-AG/connectors/issues/832)) ([2444db4](https://github.com/Unique-AG/connectors/commit/2444db42d34a4f9d87dfb32f7631469767230c99))

## [0.0.2](https://github.com/Unique-AG/connectors/compare/backstop-mcp@0.0.1...backstop-mcp@0.0.2) (2026-08-19)


### Features

* **backstop-mcp,main:** pull contact details and opportunities, and describe what we return ([#809](https://github.com/Unique-AG/connectors/issues/809)) ([b1157f8](https://github.com/Unique-AG/connectors/commit/b1157f8b8d3378faf062d0aea556dccb68abafe5))
* **backstop-mcp:** add `get_product_positions` and `get_accounts_for_party` ([#812](https://github.com/Unique-AG/connectors/issues/812)) ([fcd0e26](https://github.com/Unique-AG/connectors/commit/fcd0e26929a2075be750a2168cc16e6016339d08))
* **backstop-mcp:** carry the resource id on every projected include ([#811](https://github.com/Unique-AG/connectors/issues/811)) ([b4bec0b](https://github.com/Unique-AG/connectors/commit/b4bec0b428fa86c5aec8ff21b1cc39c9e142515f))

## 0.0.1 (2026-08-17)


### Features

* **backstop-mcp,ci,scripts,main:** scaffold Backstop MCP service shell ([#716](https://github.com/Unique-AG/connectors/issues/716)) ([39e7011](https://github.com/Unique-AG/connectors/commit/39e70111883492378b37f0f377338961e13caf17))
* **backstop-mcp,main:** fetch custom fields on demand instead of glossary prefetch ([#795](https://github.com/Unique-AG/connectors/issues/795)) ([4077ab7](https://github.com/Unique-AG/connectors/commit/4077ab7a2cba4e098f43c53f7296121e7864d8e7))
* **backstop-mcp:** add activity history timeline over merged activity and email streams ([#794](https://github.com/Unique-AG/connectors/issues/794)) ([71ba779](https://github.com/Unique-AG/connectors/commit/71ba7795eb327be78b00aa6ae4e2ad901661d10b))
* **backstop-mcp:** add Backstop HTTP client and OAuth credential bridge ([#748](https://github.com/Unique-AG/connectors/issues/748)) ([17b9c35](https://github.com/Unique-AG/connectors/commit/17b9c355bab4b613d196d50be0609952e13db337))
* **backstop-mcp:** add custom-field schema discovery library ([#750](https://github.com/Unique-AG/connectors/issues/750)) ([a2dbafb](https://github.com/Unique-AG/connectors/commit/a2dbafb89c9e6e6339014fbd30fa8b9320b25bc5))
* **backstop-mcp:** add data hygiene and MCP tool surface ([#793](https://github.com/Unique-AG/connectors/issues/793)) ([21734c3](https://github.com/Unique-AG/connectors/commit/21734c348aabe2919132be14c0ff0b4068ebd53b))
* **backstop-mcp:** add party ID resolver library ([#749](https://github.com/Unique-AG/connectors/issues/749)) ([3bcb9b6](https://github.com/Unique-AG/connectors/commit/3bcb9b648e68aa47240f417ff80c85208da11119))
