# Changelog

## [2.1.0](https://github.com/Unique-AG/connectors/compare/confluence-connector@2.0.1...confluence-connector@2.1.0) (2026-06-03)


### Features

* **confluence-connector:** add HTTP Basic auth for data-center ([#597](https://github.com/Unique-AG/connectors/issues/597)) ([75b8beb](https://github.com/Unique-AG/connectors/commit/75b8beb714f2b61ebe510c895f3a82754e705849))

## [2.0.1](https://github.com/Unique-AG/connectors/compare/confluence-connector@2.0.0...confluence-connector@2.0.1) (2026-06-03)


### Bug Fixes

* **confluence-connector:** include release name in ConfigMap names ([#596](https://github.com/Unique-AG/connectors/issues/596)) ([722c6f6](https://github.com/Unique-AG/connectors/commit/722c6f6caa894383f18b48c06e6a60286f72379e))

## [2.0.0](https://github.com/Unique-AG/connectors/compare/confluence-connector@2.0.0-alpha.8...confluence-connector@2.0.0) (2026-05-15)


### Bug Fixes

* **confluence-connector:** bump to 2.0.0 ([#551](https://github.com/Unique-AG/connectors/issues/551)) ([ebe5b74](https://github.com/Unique-AG/connectors/commit/ebe5b74573106de785129b470bb795e3341b143d))
* **confluence-connector:** release as 2.0.0 ([#553](https://github.com/Unique-AG/connectors/issues/553)) ([85d72b7](https://github.com/Unique-AG/connectors/commit/85d72b7c1b508b7a027f1e8813989a5f38d6fb3a))


### Tests

* **confluence-connector:** cover parseScopeExternalId prefix-only input ([#555](https://github.com/Unique-AG/connectors/issues/555)) ([4d2e4bf](https://github.com/Unique-AG/connectors/commit/4d2e4bf31c117981cce062b92abd6a6a44900d3d))

## [2.0.0-alpha.8](https://github.com/Unique-AG/connectors/compare/confluence-connector@2.0.0-alpha.7...confluence-connector@2.0.0-alpha.8) (2026-05-15)


### Features

* **confluence-connector,unique-api,main:** migrate child scopes when root scopeId changes ([#506](https://github.com/Unique-AG/connectors/issues/506)) ([ad4c9ac](https://github.com/Unique-AG/connectors/commit/ad4c9ac20aa6f5d40ca4d53585960e91ae6085ec))


### Bug Fixes

* **confluence-connector,unique-api,utils,logger,deps:** sanitize errors in logging ([#488](https://github.com/Unique-AG/connectors/issues/488)) ([74044db](https://github.com/Unique-AG/connectors/commit/74044db824bf0e792395502beed2e80b473e2ce7))

## [2.0.0-alpha.7](https://github.com/Unique-AG/connectors/compare/confluence-connector@2.0.0-alpha.6...confluence-connector@2.0.0-alpha.7) (2026-04-29)


### ⚠ BREAKING CHANGES

* **confluence-connector,unique-api:** `ingestion.attachments.allowedExtensions` has been renamed to `ingestion.attachments.allowedMimeTypes` and now expects MIME type strings instead of file extensions. Operators with custom values in their tenant YAML must migrate. Default values are now MIME types covering PDF, DOCX, XLSX, PPTX, plain text, CSV, HTML, PNG, and JPEG. Legacy `.ppt` (Office 97-2003, `application/vnd.ms-powerpoint`) is no longer in defaults; it was previously matched by extension but rejected by `node-ingestion`'s public API gate, so it was already non-functional end-to-end. The connector is still alpha (`prerelease: true`), so no compatibility shim is provided.

### Features

* **confluence-connector,deps:** add /health endpoint with sync, connectivity, and Unique API indicators ([#493](https://github.com/Unique-AG/connectors/issues/493)) ([e41c707](https://github.com/Unique-AG/connectors/commit/e41c70723dcd9104e3432b6cfa0c1aa852618f40))
* **confluence-connector,unique-api:** implement content cleanup for deleted tenants ([#370](https://github.com/Unique-AG/connectors/issues/370)) ([0fbcbdf](https://github.com/Unique-AG/connectors/commit/0fbcbdf0e4ecaeef4bf86aa7f4562efc315a7162))
* **confluence-connector,unique-api:** ingest images and switch attachment filter to MIME types ([#494](https://github.com/Unique-AG/connectors/issues/494)) ([530caee](https://github.com/Unique-AG/connectors/commit/530caeeb4735ef19bda8e246ec2c9b0811eb29de))


### Bug Fixes

* **confluence-connector:** downgrade noisy skip logs to debug level ([#481](https://github.com/Unique-AG/connectors/issues/481)) ([8233745](https://github.com/Unique-AG/connectors/commit/82337452a50fbc4986ddd04be3a67c5443f5ce5a))
* **confluence-connector:** improve observability during long syncs ([#482](https://github.com/Unique-AG/connectors/issues/482)) ([cb5310e](https://github.com/Unique-AG/connectors/commit/cb5310e877a8b9024859dcff073aaf6d696a5a4d))
* **confluence-connector:** namespace dashboard configmap key to avoid sidecar file collision ([#483](https://github.com/Unique-AG/connectors/issues/483)) ([c45627a](https://github.com/Unique-AG/connectors/commit/c45627ae82521df46a9299973cd8331cb2656a55))
* **confluence-connector:** request JSON from DC applinks manifest endpoint ([#484](https://github.com/Unique-AG/connectors/issues/484)) ([bd3cd23](https://github.com/Unique-AG/connectors/commit/bd3cd23233881d66ba0b823c7062dac4ebeef4e6))

## [2.0.0-alpha.6](https://github.com/Unique-AG/connectors/compare/confluence-connector@2.0.0-alpha.5...confluence-connector@2.0.0-alpha.6) (2026-04-17)


### Bug Fixes

* **confluence-connector:** add typeid-js dependency required by @unique-ag/utils/zod ([#480](https://github.com/Unique-AG/connectors/issues/480)) ([6370be9](https://github.com/Unique-AG/connectors/commit/6370be948ffefbdde5b2920c1b5b08a2cb903d40))

## [2.0.0-alpha.5](https://github.com/Unique-AG/connectors/compare/confluence-connector@2.0.0-alpha.4...confluence-connector@2.0.0-alpha.5) (2026-04-17)


### Features

* **confluence-connector,utils,deps:** add HTTP proxy support ([#394](https://github.com/Unique-AG/connectors/issues/394)) ([ddee2ca](https://github.com/Unique-AG/connectors/commit/ddee2ca32c6474f1d0c2fa4ac4bf8908ab1ee6df))
* **confluence-connector:** add metrics and Grafana dashboard ([#395](https://github.com/Unique-AG/connectors/issues/395)) ([cb765d5](https://github.com/Unique-AG/connectors/commit/cb765d5a6897073cc566eed3a6a7e6676e625ef1))
* **confluence-connector:** set external ID on root scope and validate instance ownership ([#435](https://github.com/Unique-AG/connectors/issues/435)) ([2ffeb74](https://github.com/Unique-AG/connectors/commit/2ffeb74c29dd9fb7b009c647eb48ed083af60c28))


### Bug Fixes

* **confluence-connector:** allow deletion guard to pass when new files are being added ([#368](https://github.com/Unique-AG/connectors/issues/368)) ([b57683c](https://github.com/Unique-AG/connectors/commit/b57683c27d13c32c847758cb77be52c65a00dcfa))
* **confluence-connector:** clean up orphaned files and scopes when spaces are removed ([#421](https://github.com/Unique-AG/connectors/issues/421)) ([b72b99d](https://github.com/Unique-AG/connectors/commit/b72b99d70e07b6e568680173dabc74d54c05f18c))
* **confluence-connector:** clean up registered content after failed upload or finalization ([#381](https://github.com/Unique-AG/connectors/issues/381)) ([b78cebb](https://github.com/Unique-AG/connectors/commit/b78cebb2017726f653901392a2561b618399d6a1))
* **confluence-connector:** remove os_authType=basic from Data Center API URLs ([#457](https://github.com/Unique-AG/connectors/issues/457)) ([542ff07](https://github.com/Unique-AG/connectors/commit/542ff074aa8ce4b050bede6092a62e350763d292))
* **deps:** enable stripLeadingPaths in SWC builder for all services ([#458](https://github.com/Unique-AG/connectors/issues/458)) ([caa3abc](https://github.com/Unique-AG/connectors/commit/caa3abc26b9aea44dede0ce89101df64b3f97b77))
* **deps:** resolve Dependabot security alerts for multiple transitive dependencies ([#449](https://github.com/Unique-AG/connectors/issues/449)) ([c800b51](https://github.com/Unique-AG/connectors/commit/c800b51439145282cababd491a6fba1a84a748a9))
* **deps:** resolve Dependabot security alerts for undici, path-to-regexp, orval, minimatch, and brace-expansion ([#432](https://github.com/Unique-AG/connectors/issues/432)) ([5cd9c0f](https://github.com/Unique-AG/connectors/commit/5cd9c0fdc3230de591b28574fccabb7df2cd2cce))
* **deps:** resolve Dependabot security alerts related to jsonwebtoken, js-yaml and @nestjs/ libraries ([#446](https://github.com/Unique-AG/connectors/issues/446)) ([44835ec](https://github.com/Unique-AG/connectors/commit/44835ec851589e2288fd2e1551ca22edb148190e))
* **deps:** upgrade nestjs-otel to v8 to resolve systeminformation CVEs ([#471](https://github.com/Unique-AG/connectors/issues/471)) ([ec584a9](https://github.com/Unique-AG/connectors/commit/ec584a95427b3a9989387c548d654c8b4fbbd775))

## [2.0.0-alpha.4](https://github.com/Unique-AG/connectors/compare/confluence-connector@2.0.0-alpha.3...confluence-connector@2.0.0-alpha.4) (2026-03-17)


### Features

* **confluence-connector:** file attachment ingestion ([#358](https://github.com/Unique-AG/connectors/issues/358)) ([69cdaff](https://github.com/Unique-AG/connectors/commit/69cdaff68bd972ec84e09e21d1cbc630239e3d42))

## [2.0.0-alpha.3](https://github.com/Unique-AG/connectors/compare/confluence-connector@2.0.0-alpha.2...confluence-connector@2.0.0-alpha.3) (2026-03-16)


### Bug Fixes

* **confluence-connector:** align v2 with v1 for DC space types, label sorting, and blog posts ([#350](https://github.com/Unique-AG/connectors/issues/350)) ([73698f3](https://github.com/Unique-AG/connectors/commit/73698f31b707e0f9cd56305bf9ad10acb667199b))
* **confluence-connector:** bring in the totalFilesInUnique deletion guard logic from sharepoint-connector ([#347](https://github.com/Unique-AG/connectors/issues/347)) ([af98e39](https://github.com/Unique-AG/connectors/commit/af98e390dad18624987d086e9d3e18909a294e2e))

## [2.0.0-alpha.2](https://github.com/Unique-AG/connectors/compare/confluence-connector@2.0.0-alpha.1...confluence-connector@2.0.0-alpha.2) (2026-03-10)


### Bug Fixes

* **confluence-connector:** correctWriteUrl when using cluster_local ([#345](https://github.com/Unique-AG/connectors/issues/345)) ([2bde377](https://github.com/Unique-AG/connectors/commit/2bde37745f499c1d2b88ffbe9ad8e7439e12ff09))

## [2.0.0-alpha.1](https://github.com/Unique-AG/connectors/compare/confluence-connector@2.0.0-alpha.0...confluence-connector@2.0.0-alpha.1) (2026-03-10)


### ⚠ BREAKING CHANGES

* **sharepoint-connector,outlook-mcp,factset-mcp:** all git tags no longer include the version 'v'. In a future version, all releases will also not include the v anymore.

### Features

* **confluence-connector,ci,main,deps:** scaffold NestJS project with tenant configuration loading ([#258](https://github.com/Unique-AG/connectors/issues/258)) ([63713b7](https://github.com/Unique-AG/connectors/commit/63713b7dc0d260ceb5e29ceb32196adc4147e717))
* **confluence-connector,deps:** implement multi-tenancy and confluence scanning for DC and Cloud ([#284](https://github.com/Unique-AG/connectors/issues/284)) ([e0f8703](https://github.com/Unique-AG/connectors/commit/e0f87038caf4825d390d51307a8270019183b501))
* **confluence-connector,unique-api,utils,deps:** implement ingestion pipeline ([#305](https://github.com/Unique-AG/connectors/issues/305)) ([7d2c64c](https://github.com/Unique-AG/connectors/commit/7d2c64c1f4248e06a822a7d827715c4ae001eeec))
* **confluence-connector:** add Terraform module for Key Vault secret provisioning ([#339](https://github.com/Unique-AG/connectors/issues/339)) ([ce2241e](https://github.com/Unique-AG/connectors/commit/ce2241ebb8614640f3c7cdb5a6e35a2f17c344a3))
* **sharepoint-connector,outlook-mcp,factset-mcp:** remove v in tags ([#168](https://github.com/Unique-AG/connectors/issues/168)) ([2f56700](https://github.com/Unique-AG/connectors/commit/2f5670000c968d8bf0e0051eeb47766f586c84cc))
