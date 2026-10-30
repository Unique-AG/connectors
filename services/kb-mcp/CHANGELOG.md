# Changelog

## [0.1.8](https://github.com/Unique-AG/connectors/compare/kb-mcp@0.1.7...kb-mcp@0.1.8) (2026-10-30)


### Features

* **architecture-demo-mcp,ci,exp-kyckr-mcp,exp-tiingo-mcp,hello-mcp,kb-mcp,main,mcp-architecture,mcp-configs,mcp-observability,mcp-openapi,mcp-scaffold,scripts:** generate Python MCPs from one skeleton that enforces the architecture ([#1251](https://github.com/Unique-AG/connectors/issues/1251)) ([8ca8bde](https://github.com/Unique-AG/connectors/commit/8ca8bdef6925adcc0dd61d9f7cb6f8e10e3635e1))


### Bug Fixes

* **architecture-demo-mcp,backstop-mcp,confluence-connector,hello-mcp,kb-mcp,main,mcp-scaffold,office-365-mcp,outlook-semantic-mcp,sharepoint-connector,teams-mcp,with-intelligence-mcp:** run migrations as argo cd sync hooks after the database ([#1360](https://github.com/Unique-AG/connectors/issues/1360)) ([5264f9f](https://github.com/Unique-AG/connectors/commit/5264f9f14505bbc57d01fe676946daaf63e261f3))
* **architecture-demo-mcp,backstop-mcp,confluence-connector,hello-mcp,kb-mcp,office-365-mcp,outlook-semantic-mcp,sharepoint-connector,teams-mcp,with-intelligence-mcp:** bump base chart for network policy sync-wave ordering ([#1307](https://github.com/Unique-AG/connectors/issues/1307)) ([8e9eba5](https://github.com/Unique-AG/connectors/commit/8e9eba588c9052ef87a356a0bd9c575170848ca2))
* **kb-mcp:** close zitadel and tiktoken egress gaps in network policy ([#1283](https://github.com/Unique-AG/connectors/issues/1283)) ([19e837a](https://github.com/Unique-AG/connectors/commit/19e837a26c4d575d9b4eb25bf01c4570e17f2f15))
* **main:** vulna squash MAJOR VERSION BUMP pillow 12.3.0 to 13.0.0 ([#1296](https://github.com/Unique-AG/connectors/issues/1296)) ([1704f7c](https://github.com/Unique-AG/connectors/commit/1704f7c9a36082c6deff1615b1dfbf3a55b48ac0))


### Dependencies

* **architecture-demo-mcp,backstop-mcp,ci,exp-kyckr-mcp,exp-tiingo-mcp,hello-mcp,kb-mcp,mcp-openapi,mcp-scaffold,office-365-mcp,with-intelligence-mcp:** pin one version of each shared dependency ([#1291](https://github.com/Unique-AG/connectors/issues/1291)) ([a5cfdb8](https://github.com/Unique-AG/connectors/commit/a5cfdb8fc888e64a212fdf6dbe0457a453737ccf))
* **architecture-demo-mcp,backstop-mcp,exp-kyckr-mcp,exp-tiingo-mcp,hello-mcp,kb-mcp,main,mcp-configs,mcp-credential-auth,mcp-observability,mcp-openapi,mcp-scaffold,office-365-mcp,with-intelligence-mcp:** give every Python project the same poe tasks ([#1292](https://github.com/Unique-AG/connectors/issues/1292)) ([71547e7](https://github.com/Unique-AG/connectors/commit/71547e7c1f447d8eefe270b076f91129514cd96c))
* **architecture-demo-mcp,backstop-mcp,exp-kyckr-mcp,exp-tiingo-mcp,hello-mcp,kb-mcp,mcp-architecture,mcp-configs,mcp-credential-auth,mcp-observability,mcp-openapi,mcp-scaffold,office-365-mcp,with-intelligence-mcp:** require Python 3.14 and resolve one version of every package in every lock ([#1293](https://github.com/Unique-AG/connectors/issues/1293)) ([8f0a04b](https://github.com/Unique-AG/connectors/commit/8f0a04b87a2c33a0b0cb191dbee7f74286b2d1f1))
* **main:** refresh dependencies and drop unneeded overrides ([#1322](https://github.com/Unique-AG/connectors/issues/1322)) ([a4f2390](https://github.com/Unique-AG/connectors/commit/a4f239000fc35b5809f6c7b50c920ac3c8419ef9))

## [0.1.7](https://github.com/Unique-AG/connectors/compare/kb-mcp@0.1.6...kb-mcp@0.1.7) (2026-10-23)


### Features

* **kb-mcp:** add icons for the MCP server and its tools ([#1172](https://github.com/Unique-AG/connectors/issues/1172)) ([e90f728](https://github.com/Unique-AG/connectors/commit/e90f728a3556dbaaa6dac39551c338e2512f92d3))


### Bug Fixes

* **backstop-mcp,kb-mcp,office-365-mcp,with-intelligence-mcp,exp-kyckr-mcp,exp-tiingo-mcp,mcp-credential-auth:** drop compromised eMudhra CA roots ([#1268](https://github.com/Unique-AG/connectors/issues/1268)) ([1f81406](https://github.com/Unique-AG/connectors/commit/1f814060865c9af03a60957b8a57242d9f08d422))


### Dependencies

* bump basedpyright in /* ([#1192](https://github.com/Unique-AG/connectors/issues/1192)) ([5c0cf09](https://github.com/Unique-AG/connectors/commit/5c0cf0965c6d476057e2f63373b753385b81d218))
* bump cryptography in /* ([#1189](https://github.com/Unique-AG/connectors/issues/1189)) ([b2f3689](https://github.com/Unique-AG/connectors/commit/b2f3689c6f4c342bc2e05b4795bf9f552196e572))
* bump fastmcp in /* ([#1198](https://github.com/Unique-AG/connectors/issues/1198)) ([9108152](https://github.com/Unique-AG/connectors/commit/9108152e00405dcb49e1ccf4d17a703a7e4acb79))
* bump mcp in /* ([#1191](https://github.com/Unique-AG/connectors/issues/1191)) ([576fcad](https://github.com/Unique-AG/connectors/commit/576fcad8912cef078f6241f78d13620377e0d159))
* bump pydantic in /services/* ([#1238](https://github.com/Unique-AG/connectors/issues/1238)) ([01801d2](https://github.com/Unique-AG/connectors/commit/01801d2b560ef29bdced07bbe1101cc8fd655457))
* bump python in /services/*/deploy ([#1140](https://github.com/Unique-AG/connectors/issues/1140)) ([ecc36dc](https://github.com/Unique-AG/connectors/commit/ecc36dc232dfbfbaba7dd093cf2aa587cacb2297))
* bump python in /services/*/deploy ([#1229](https://github.com/Unique-AG/connectors/issues/1229)) ([c5e1f49](https://github.com/Unique-AG/connectors/commit/c5e1f49ff2c9fce8ef01561463d193b6f627c81b))
* bump ruff in /* ([#1193](https://github.com/Unique-AG/connectors/issues/1193)) ([ac0d4c2](https://github.com/Unique-AG/connectors/commit/ac0d4c21318fe86aec8317a8215fd823250f6fe7))
* bump ruff in /packages/* ([#1241](https://github.com/Unique-AG/connectors/issues/1241)) ([fe61f41](https://github.com/Unique-AG/connectors/commit/fe61f410134445384ce6f5de5ed25edbb249c34e))
* **deps:** move pinned vulnerable dependencies to patched versions ([#1200](https://github.com/Unique-AG/connectors/issues/1200)) ([531d6e0](https://github.com/Unique-AG/connectors/commit/531d6e0d8625cd25014ea8b056475f550af27902))
* **deps:** refresh all transitive dependencies ([#1201](https://github.com/Unique-AG/connectors/issues/1201)) ([68a747d](https://github.com/Unique-AG/connectors/commit/68a747dc8df80f05ba8a5dc5a5caacf111af446f))
* **with-intelligence-mcp,backstop-mcp,hello-mcp,kb-mcp,office-365-mcp,ci,scripts,deps:** add deployment and release ([#988](https://github.com/Unique-AG/connectors/issues/988)) ([55f48cd](https://github.com/Unique-AG/connectors/commit/55f48cd2e2676601c5f3d6590a8990c6986c5132))

## [0.1.6](https://github.com/Unique-AG/connectors/compare/kb-mcp@0.1.5...kb-mcp@0.1.6) (2026-09-29)


### Features

* **kb-mcp,main:** ship the unique-kb-mcp agent skill ([#1083](https://github.com/Unique-AG/connectors/issues/1083)) ([875a1c7](https://github.com/Unique-AG/connectors/commit/875a1c756ecf9c606d352e00f6b6b1a1af2774fa))
* **kb-mcp:** add a chart field for the Zitadel client id ([#1081](https://github.com/Unique-AG/connectors/issues/1081)) ([5bd6abc](https://github.com/Unique-AG/connectors/commit/5bd6abcc74a78b1eb19500aff573ad8d10899aa5))
* **kb-mcp:** add params to content metadata for easier filtering ([#1085](https://github.com/Unique-AG/connectors/issues/1085)) ([6d7201a](https://github.com/Unique-AG/connectors/commit/6d7201ae8e87c05610a28667c26b92581ec4a32d))
* **kb-mcp:** cap distinct values returned per metadata field ([#1090](https://github.com/Unique-AG/connectors/issues/1090)) ([83e0e23](https://github.com/Unique-AG/connectors/commit/83e0e23d506d66b3f3a443e53cf0352756315322))


### Bug Fixes

* **kb-mcp:** cap content_tree folders, fix truncation notices ([#1082](https://github.com/Unique-AG/connectors/issues/1082)) ([3686dbe](https://github.com/Unique-AG/connectors/commit/3686dbe142f8dd732d1137bb4343474a7d411f92))
* **kb-mcp:** rename the MCP and set a connect-time icon ([#1086](https://github.com/Unique-AG/connectors/issues/1086)) ([d522c50](https://github.com/Unique-AG/connectors/commit/d522c503076f9c2a4ef833eab47caf47231094ba))


### Dependencies

* bump fastmcp in /* ([#1102](https://github.com/Unique-AG/connectors/issues/1102)) ([1cf61e2](https://github.com/Unique-AG/connectors/commit/1cf61e2c3cd7b0258e82f4be391cafca1f742bab))
* bump hatchling in /* ([#1108](https://github.com/Unique-AG/connectors/issues/1108)) ([776e037](https://github.com/Unique-AG/connectors/commit/776e037be020704fb437c471c548c16db863c2fc))
* bump ruff in /* ([#1107](https://github.com/Unique-AG/connectors/issues/1107)) ([9953c11](https://github.com/Unique-AG/connectors/commit/9953c118eeac82f79cd1eacc6038f8a35bc2569c))

## [0.1.5](https://github.com/Unique-AG/connectors/compare/kb-mcp@0.1.4...kb-mcp@0.1.5) (2026-09-21)


### Features

* **kb-mcp:** add the content_metadata tool and scope the folder walk ([#1079](https://github.com/Unique-AG/connectors/issues/1079)) ([c563a03](https://github.com/Unique-AG/connectors/commit/c563a0334e9f15d0d61c42006cdd1129b8175ff5))
* **kb-mcp:** allow UniqueQL metadata filters and read_file token overrides ([#1014](https://github.com/Unique-AG/connectors/issues/1014)) ([4788898](https://github.com/Unique-AG/connectors/commit/4788898044f443cf7c9bfbc91c6a39b44b7b17e5))


### Bug Fixes

* **backstop-mcp,hello-mcp,kb-mcp,office-365-mcp:** align the Python image build layouts ([#1038](https://github.com/Unique-AG/connectors/issues/1038)) ([ecdffb6](https://github.com/Unique-AG/connectors/commit/ecdffb656c2f9ed98217c2f4215b33bb9751efd9))


### Dependencies

* **backstop-mcp,hello-mcp,kb-mcp,office-365-mcp:** remove pip from the Python images ([#1033](https://github.com/Unique-AG/connectors/issues/1033)) ([3c0c51f](https://github.com/Unique-AG/connectors/commit/3c0c51f0feb886f41fcc7c6728cea9c040e30741))
* bump basedpyright in /packages/mcp-credential-auth ([#1026](https://github.com/Unique-AG/connectors/issues/1026)) ([61f0ddd](https://github.com/Unique-AG/connectors/commit/61f0dddee8a171e7d8f0398c5f23ada73f7a8b2f))
* bump mcp in /services/backstop-mcp ([#1024](https://github.com/Unique-AG/connectors/issues/1024)) ([f0f626f](https://github.com/Unique-AG/connectors/commit/f0f626fda57d873a783d7eac16e67e23f3393c02))
* bump pydantic-settings in /services/kb-mcp ([#999](https://github.com/Unique-AG/connectors/issues/999)) ([265bacf](https://github.com/Unique-AG/connectors/commit/265bacfb93ccfeda2c0ff6da71cf47457a5deafd))
* bump ruff in /packages/mcp-credential-auth ([#1028](https://github.com/Unique-AG/connectors/issues/1028)) ([bb44f5a](https://github.com/Unique-AG/connectors/commit/bb44f5a5fce11f7022bb67d12f647a25336dddb4))
* bump starlette in /services/backstop-mcp ([#1007](https://github.com/Unique-AG/connectors/issues/1007)) ([5f680b5](https://github.com/Unique-AG/connectors/commit/5f680b52b18891b35875a04d37acd0ad2e5ab49b))
* **hello-mcp,kb-mcp,office-365-mcp:** apply Debian security updates in the Python runtime images ([#1022](https://github.com/Unique-AG/connectors/issues/1022)) ([83a61f8](https://github.com/Unique-AG/connectors/commit/83a61f88d73645a607300ac9dc7ae424a5b29294))
* pin lxml to 6.1.3, bump kiota ([#1050](https://github.com/Unique-AG/connectors/issues/1050)) ([122c820](https://github.com/Unique-AG/connectors/commit/122c820f8a4a0e150318d4c58c587bd4cd0b8919))

## [0.1.4](https://github.com/Unique-AG/connectors/compare/kb-mcp@0.1.3...kb-mcp@0.1.4) (2026-09-11)


### Features

* **kb-mcp:** send service id header ([#1011](https://github.com/Unique-AG/connectors/issues/1011)) ([0bc89c3](https://github.com/Unique-AG/connectors/commit/0bc89c35ed2826c27e19171d45d77da5ff8d1d18))


### Bug Fixes

* **backstop-mcp,confluence-connector,hello-mcp,kb-mcp,office-365-mcp,outlook-semantic-mcp,sharepoint-connector,teams-mcp:** bump base chart dependency to 0.1.0-87990c ([#915](https://github.com/Unique-AG/connectors/issues/915)) ([1bc27a7](https://github.com/Unique-AG/connectors/commit/1bc27a713ab7e2a5bf36671fa1f1f294497c649e))


### Dependencies

* bump pydantic in /services/kb-mcp ([#954](https://github.com/Unique-AG/connectors/issues/954)) ([f7ea6fd](https://github.com/Unique-AG/connectors/commit/f7ea6fde3fb8d5c7e33df42494f8c369a238336a))
* bump ruff from 0.16.4 to 0.16.5 in /services/kb-mcp ([#932](https://github.com/Unique-AG/connectors/issues/932)) ([45650b0](https://github.com/Unique-AG/connectors/commit/45650b0b1692c7603b26f5425918a2cd3e7a959b))
* bump ruff in /services/backstop-mcp ([#953](https://github.com/Unique-AG/connectors/issues/953)) ([3222aa2](https://github.com/Unique-AG/connectors/commit/3222aa2cf86c70f960674f48771f610d13eaf425))
* **kb-mcp:** bump python-dotenv to 1.2.3 ([#977](https://github.com/Unique-AG/connectors/issues/977)) ([f316877](https://github.com/Unique-AG/connectors/commit/f316877bb66ffedfa2a2188ba5b8dafe487308fc))
* put every dependency in the right group, name what was missing, and hold shared versions in the pnpm catalog ([#958](https://github.com/Unique-AG/connectors/issues/958)) ([794092f](https://github.com/Unique-AG/connectors/commit/794092faa348052eddf2be580ed61fc771684b6f))
* upgrade backstop-mcp and kb-mcp to fastmcp 4.0.3 ([#971](https://github.com/Unique-AG/connectors/issues/971)) ([569f04c](https://github.com/Unique-AG/connectors/commit/569f04c1a6c3a1b046e36c5c70fb5319949c139b))
* upgrade uv to 0.12.10 in the Python images ([#975](https://github.com/Unique-AG/connectors/issues/975)) ([8fe0852](https://github.com/Unique-AG/connectors/commit/8fe08523405ddcacfd3fd616758bb8a306855079))

## [0.1.3](https://github.com/Unique-AG/connectors/compare/kb-mcp@0.1.2...kb-mcp@0.1.3) (2026-09-03)


### Bug Fixes

* **kb-mcp:** bound content-tree resources and authentication ([#895](https://github.com/Unique-AG/connectors/issues/895)) ([8c4550a](https://github.com/Unique-AG/connectors/commit/8c4550a937a0ff51d518108996358556bd85da02))
* **kb-mcp:** resolve read_file's file-type dispatch from mime_type ([#878](https://github.com/Unique-AG/connectors/issues/878)) ([b38623d](https://github.com/Unique-AG/connectors/commit/b38623dfc2b1b50db6196e45219c2a8cba1f3ee1))

## [0.1.2](https://github.com/Unique-AG/connectors/compare/kb-mcp@0.1.1...kb-mcp@0.1.2) (2026-08-31)


### Features

* **kb-mcp:** add a KB_MCP_ENABLED_TOOLS allowlist to ship search-only ([#872](https://github.com/Unique-AG/connectors/issues/872)) ([6289cdb](https://github.com/Unique-AG/connectors/commit/6289cdbf802337845a01b890ace9f20ec7acfbe7))


### Bug Fixes

* **ci,main,hello-mcp,kb-mcp:** keep uv.lock's version in step with pyproject on release ([#856](https://github.com/Unique-AG/connectors/issues/856)) ([12c8512](https://github.com/Unique-AG/connectors/commit/12c851201e87962dff51072d14f70e7570ae99a2))

## [0.1.1](https://github.com/Unique-AG/connectors/compare/kb-mcp@0.1.0...kb-mcp@0.1.1) (2026-08-14)


### Bug Fixes

* **kb-mcp:** return ToolResult and wire [sourceN] references [UN-24212] ([#781](https://github.com/Unique-AG/connectors/issues/781)) ([573c9bc](https://github.com/Unique-AG/connectors/commit/573c9bcf3ba51114e5077d76c40393be55f7d19b))

## [0.1.0](https://github.com/Unique-AG/connectors/compare/kb-mcp@0.0.1...kb-mcp@0.1.0) (2026-08-11)


### ⚠ BREAKING CHANGES

* **sharepoint-connector,outlook-mcp,factset-mcp:** all git tags no longer include the version 'v'. In a future version, all releases will also not include the v anymore.

### Features

* **kb-mcp,ci,scripts,main:** migrate Knowledge Base Search MCP into connectors as kb-mcp ([#719](https://github.com/Unique-AG/connectors/issues/719)) ([82b79a8](https://github.com/Unique-AG/connectors/commit/82b79a8667c083ea53f03c89d40e9307e6b067ea))
* **sharepoint-connector,outlook-mcp,factset-mcp:** remove v in tags ([#168](https://github.com/Unique-AG/connectors/issues/168)) ([2f56700](https://github.com/Unique-AG/connectors/commit/2f5670000c968d8bf0e0051eeb47766f586c84cc))


### Bug Fixes

* **kb-mcp:** persist OAuth state in Postgres and address PR [#719](https://github.com/Unique-AG/connectors/issues/719) review feedback ([#756](https://github.com/Unique-AG/connectors/issues/756)) ([25e8cdb](https://github.com/Unique-AG/connectors/commit/25e8cdb08aafaeae2e7c3a36de102fc15295a285))
