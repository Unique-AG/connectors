# Changelog

## [0.2.3](https://github.com/Unique-AG/connectors/compare/factset-mcp@v0.2.2...factset-mcp@v0.2.3) (2025-10-20)


### Bug Fixes

* **factset:** upgrade Prisma to fix incompatible Prisma versions ([#69](https://github.com/Unique-AG/connectors/issues/69)) ([2586805](https://github.com/Unique-AG/connectors/commit/2586805e33fcbf810a1b7d8e588288b2fbc4d76f))

## [0.2.2](https://github.com/Unique-AG/connectors/compare/factset-mcp@v0.2.1...factset-mcp@v0.2.2) (2025-10-18)


### Features

* extend outlook and factset with prompts ([#24](https://github.com/Unique-AG/connectors/issues/24)) ([a11e85a](https://github.com/Unique-AG/connectors/commit/a11e85a4113b4e50d4467936eb415b0666ef3071))
* **factset:** add module to deploy to new tenants ([#27](https://github.com/Unique-AG/connectors/issues/27)) ([7095493](https://github.com/Unique-AG/connectors/commit/70954930750ee8bdcd3a9cf6b53749f3b1ff9ff0))
* **factset:** remove prompts until we have an allowlist ([#66](https://github.com/Unique-AG/connectors/issues/66)) ([069f15f](https://github.com/Unique-AG/connectors/commit/069f15f47613297dd5873ca9153f4d82e4421406))
* **outlook:** add some tests (AI generated) ([#21](https://github.com/Unique-AG/connectors/issues/21)) ([71c8d16](https://github.com/Unique-AG/connectors/commit/71c8d160df6275dfe428a7a017ac415dd3c282a6))
* **outlook:** switch to Drizzle ORM ([#30](https://github.com/Unique-AG/connectors/issues/30)) ([26261c3](https://github.com/Unique-AG/connectors/commit/26261c3d28ec98296a46438e39953b43b3b817eb))
* release new mcp server versions ([#25](https://github.com/Unique-AG/connectors/issues/25)) ([d2cb306](https://github.com/Unique-AG/connectors/commit/d2cb3063e72953a709fe36871a1f9ebf0b8b5f56))
* restructure infra components to streamline ([#28](https://github.com/Unique-AG/connectors/issues/28)) ([21245a9](https://github.com/Unique-AG/connectors/commit/21245a9c933816be9e29df183444fc2f3b6c5d3e))
* **terraform:** refactor all modules into folders ([69b07e0](https://github.com/Unique-AG/connectors/commit/69b07e05f6277fcd08d98df1691cd7833b9c2e4d))


### Bug Fixes

* downgrade Prisma to 6.15.0 to avoid migration issues ([#26](https://github.com/Unique-AG/connectors/issues/26)) ([50e042f](https://github.com/Unique-AG/connectors/commit/50e042f2fad364201cb1f24fa1bb911d1ab4e9a5))
* tsconfig rootDir so dist output is in correct flat folder ([#22](https://github.com/Unique-AG/connectors/issues/22)) ([f2ca1c0](https://github.com/Unique-AG/connectors/commit/f2ca1c03304d909c220b37b319032910dc43d027))
* turn off migrations to be able to release latest version ([a3d6718](https://github.com/Unique-AG/connectors/commit/a3d6718a2f51b64f0f382aeaa9ebdfa48a53ddde))
