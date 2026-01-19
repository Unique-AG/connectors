## Changelog

## [0.6.0](https://github.com/Unique-AG/connectors/compare/outlook-mcp@v0.5.1...outlook-mcp@0.6.0) (2026-01-19)


### ⚠ BREAKING CHANGES

* **sharepoint-connector,outlook-mcp,factset-mcp:** all git tags no longer include the version 'v'. In a future version, all releases will also not include the v anymore.

### Features

* **sharepoint-connector,outlook-mcp,factset-mcp:** remove v in tags ([#168](https://github.com/Unique-AG/connectors/issues/168)) ([2f56700](https://github.com/Unique-AG/connectors/commit/2f5670000c968d8bf0e0051eeb47766f586c84cc))


### Bug Fixes

* **outlook:** Fixes the MCP connector to work with the v1.25.2 sdk ([#213](https://github.com/Unique-AG/connectors/issues/213)) ([52e028b](https://github.com/Unique-AG/connectors/commit/52e028b890f249907331e005ca97e770db5b95d1))

## [0.5.1](https://github.com/Unique-AG/connectors/compare/outlook-mcp@v0.5.0...outlook-mcp@v0.5.1) (2025-10-14)


### Features

* extend outlook and factset with prompts ([#24](https://github.com/Unique-AG/connectors/issues/24)) ([a11e85a](https://github.com/Unique-AG/connectors/commit/a11e85a4113b4e50d4467936eb415b0666ef3071))
* **outlook:** add some tests (AI generated) ([#21](https://github.com/Unique-AG/connectors/issues/21)) ([71c8d16](https://github.com/Unique-AG/connectors/commit/71c8d160df6275dfe428a7a017ac415dd3c282a6))
* **outlook:** bump version to 0.5.0; add changelog ([407217f](https://github.com/Unique-AG/connectors/commit/407217f24d103d626f93e75c33339baa8432bea8))
* **outlook:** remove prompts until we have an allowlist for prompts ([#63](https://github.com/Unique-AG/connectors/issues/63)) ([4d0ccd3](https://github.com/Unique-AG/connectors/commit/4d0ccd35083555f18bb19442e8e9b6b8e23e61d6))
* **outlook:** switch to Drizzle ORM ([#30](https://github.com/Unique-AG/connectors/issues/30)) ([26261c3](https://github.com/Unique-AG/connectors/commit/26261c3d28ec98296a46438e39953b43b3b817eb))
* release new mcp server versions ([#25](https://github.com/Unique-AG/connectors/issues/25)) ([d2cb306](https://github.com/Unique-AG/connectors/commit/d2cb3063e72953a709fe36871a1f9ebf0b8b5f56))
* restructure infra components to streamline ([#28](https://github.com/Unique-AG/connectors/issues/28)) ([21245a9](https://github.com/Unique-AG/connectors/commit/21245a9c933816be9e29df183444fc2f3b6c5d3e))
* **spc:** add helm chart ([#37](https://github.com/Unique-AG/connectors/issues/37)) ([962c6b2](https://github.com/Unique-AG/connectors/commit/962c6b2fdf1f632983e18d0aa244b46a78fa4f05))
* **terraform:** refactor all modules into folders ([69b07e0](https://github.com/Unique-AG/connectors/commit/69b07e05f6277fcd08d98df1691cd7833b9c2e4d))


### Bug Fixes

* downgrade Prisma to 6.15.0 to avoid migration issues ([#26](https://github.com/Unique-AG/connectors/issues/26)) ([50e042f](https://github.com/Unique-AG/connectors/commit/50e042f2fad364201cb1f24fa1bb911d1ab4e9a5))
* **outlook:** fix broken version-bump script after chart move ([9e26d2f](https://github.com/Unique-AG/connectors/commit/9e26d2f8a1923743675218a01df2363e8c818316))
* tsconfig rootDir so dist output is in correct flat folder ([#22](https://github.com/Unique-AG/connectors/issues/22)) ([f2ca1c0](https://github.com/Unique-AG/connectors/commit/f2ca1c03304d909c220b37b319032910dc43d027))
* turn off migrations to be able to release latest version ([a3d6718](https://github.com/Unique-AG/connectors/commit/a3d6718a2f51b64f0f382aeaa9ebdfa48a53ddde))

### 0.5.0 — 2025-09-16
- feat: migrate to Drizzle ORM (#27)

### 0.4.1 — 2025-09-11
- fix: downgrade Prisma to 6.15.0 to avoid migration issues (#26)

### 0.4.0 — 2025-09-11
- feat: extend Outlook and FactSet with prompts (#24)

### 0.3.5 — 2025-09-09
- fix: tsconfig rootDir so dist output is in correct flat folder (#22)

### 0.3.4 — 2025-09-09
- feat: add tests and vitest setup (AI generated) (#21)

### 0.3.3 — 2025-09-09
- chore: move server to `services/outlook-mcp` (rename from `servers`) (#20)

### 0.3.2 — 2025-09-02
- chore: add `codegen` script

### 0.3.1 — 2025-08-26
- fix: ensure metrics middleware is loaded into Graph client

### 0.3.0 — 2025-08-26
- feat: add tracing and metrics with Grafana dashboard (#11)

### 0.2.1 — 2025-08-22
- feat: add probe module for health probes

### 0.2.0 — 2025-08-22
- feat(oauth): remove cookies for state validation (#10)

### 0.1.0 — 2025-08-21
- feat: initial version
- feat: extend server with prompts, icons, and server instructions (#9)
