# Changelog

## [0.2.1](https://github.com/Unique-AG/connectors/compare/with-intelligence-mcp@0.2.0...with-intelligence-mcp@0.2.1) (2026-11-06)


### Features

* **backstop-mcp,kb-mcp,office-365-mcp,outlook-semantic-mcp,teams-mcp,with-intelligence-mcp:** advertise the new server icon in serverInfo ([#1377](https://github.com/Unique-AG/connectors/issues/1377)) ([19e8a00](https://github.com/Unique-AG/connectors/commit/19e8a009ff76826a0d606c241197cea432cfcebe))
* **mcp-server-module,mcp-observability:** rate-limit MCP tool calls per user ([#1358](https://github.com/Unique-AG/connectors/issues/1358)) ([bbe4bc0](https://github.com/Unique-AG/connectors/commit/bbe4bc07bde6b67cecee762e25a16cfeac6cc67a))
* **mcp-server-module,office-365-mcp,with-intelligence-mcp,kb-mcp:** log one audit line per MCP tool call ([#1354](https://github.com/Unique-AG/connectors/issues/1354)) ([eb7de3b](https://github.com/Unique-AG/connectors/commit/eb7de3b7c06feba5f9445e68198ba8d8fa0cf4fb))
* **with-intelligence-mcp:** redact the deployment's secrets and each caller's tokens from every log line ([#1448](https://github.com/Unique-AG/connectors/issues/1448)) ([aed880c](https://github.com/Unique-AG/connectors/commit/aed880cb378ebfc79801686c0cdfc88c9b49385c))


### Bug Fixes

* **architecture-demo-mcp,backstop-mcp,confluence-connector,hello-mcp,kb-mcp,main,mcp-scaffold,office-365-mcp,outlook-semantic-mcp,sharepoint-connector,teams-mcp,with-intelligence-mcp:** run migrations as argo cd sync hooks after the database ([#1360](https://github.com/Unique-AG/connectors/issues/1360)) ([5264f9f](https://github.com/Unique-AG/connectors/commit/5264f9f14505bbc57d01fe676946daaf63e261f3))
* **architecture-demo-mcp,backstop-mcp,confluence-connector,hello-mcp,kb-mcp,office-365-mcp,outlook-semantic-mcp,sharepoint-connector,teams-mcp,with-intelligence-mcp:** bump base chart for network policy sync-wave ordering ([#1307](https://github.com/Unique-AG/connectors/issues/1307)) ([8e9eba5](https://github.com/Unique-AG/connectors/commit/8e9eba588c9052ef87a356a0bd9c575170848ca2))
* **backstop-mcp,mcp-credential-auth,with-intelligence-mcp:** keep oauth clients that signed in once ([#1367](https://github.com/Unique-AG/connectors/issues/1367)) ([4cdd25f](https://github.com/Unique-AG/connectors/commit/4cdd25f8da0a1b6fc090c694231f1a057defde8a))
* **backstop-mcp,with-intelligence-mcp,kb-mcp,office-365-mcp:** mask unexpected tool error details ([#1344](https://github.com/Unique-AG/connectors/issues/1344)) ([5144918](https://github.com/Unique-AG/connectors/commit/5144918b0f113a024e7e19237832a315d97febce))
* **backstop-mcp,with-intelligence-mcp:** add upstream FQDN egress rules to Helm charts ([#1349](https://github.com/Unique-AG/connectors/issues/1349)) ([1849d59](https://github.com/Unique-AG/connectors/commit/1849d59d7f11562df90c71df0c55e3f701fc0477))
* deny egress to RFC1918 and link-local ranges in every MCP chart ([#1353](https://github.com/Unique-AG/connectors/issues/1353)) ([5949e66](https://github.com/Unique-AG/connectors/commit/5949e6698615dfd7de48116cd09c0550467485f1))
* **kb-mcp,with-intelligence-mcp:** filter tool arguments from debug logs ([#1347](https://github.com/Unique-AG/connectors/issues/1347)) ([7ab749e](https://github.com/Unique-AG/connectors/commit/7ab749e6620957fcf3b2f9ddf1dbaf3dd316a196))
* **main:** vulna squash MAJOR VERSION BUMP pillow 12.3.0 to 13.0.0 ([#1296](https://github.com/Unique-AG/connectors/issues/1296)) ([1704f7c](https://github.com/Unique-AG/connectors/commit/1704f7c9a36082c6deff1615b1dfbf3a55b48ac0))
* **teams-mcp,outlook-semantic-mcp,kb-mcp,backstop-mcp,with-intelligence-mcp,kyckr-mcp,temenos-mcp:** mark upstream content as untrusted in tool descriptions ([#1355](https://github.com/Unique-AG/connectors/issues/1355)) ([8aeef96](https://github.com/Unique-AG/connectors/commit/8aeef9675771f2f121e2dafae722d8bfdc4b294b))


### Dependencies

* **architecture-demo-mcp,backstop-mcp,ci,exp-kyckr-mcp,exp-tiingo-mcp,hello-mcp,kb-mcp,mcp-openapi,mcp-scaffold,office-365-mcp,with-intelligence-mcp:** pin one version of each shared dependency ([#1291](https://github.com/Unique-AG/connectors/issues/1291)) ([a5cfdb8](https://github.com/Unique-AG/connectors/commit/a5cfdb8fc888e64a212fdf6dbe0457a453737ccf))
* **architecture-demo-mcp,backstop-mcp,exp-kyckr-mcp,exp-tiingo-mcp,hello-mcp,kb-mcp,main,mcp-configs,mcp-credential-auth,mcp-observability,mcp-openapi,mcp-scaffold,office-365-mcp,with-intelligence-mcp:** give every Python project the same poe tasks ([#1292](https://github.com/Unique-AG/connectors/issues/1292)) ([71547e7](https://github.com/Unique-AG/connectors/commit/71547e7c1f447d8eefe270b076f91129514cd96c))
* **architecture-demo-mcp,backstop-mcp,exp-kyckr-mcp,exp-tiingo-mcp,hello-mcp,kb-mcp,mcp-architecture,mcp-configs,mcp-credential-auth,mcp-observability,mcp-openapi,mcp-scaffold,office-365-mcp,with-intelligence-mcp:** require Python 3.14 and resolve one version of every package in every lock ([#1293](https://github.com/Unique-AG/connectors/issues/1293)) ([8f0a04b](https://github.com/Unique-AG/connectors/commit/8f0a04b87a2c33a0b0cb191dbee7f74286b2d1f1))
* bump pillow from 12.3.0 to 13.0.0 in /services/with-intelligence-mcp ([#1271](https://github.com/Unique-AG/connectors/issues/1271)) ([a2a5f19](https://github.com/Unique-AG/connectors/commit/a2a5f1909407fa1b26b239bcf640b443cb654b9d))
* bump sqlalchemy[asyncio] in /services/backstop-mcp ([#1279](https://github.com/Unique-AG/connectors/issues/1279)) ([20a0493](https://github.com/Unique-AG/connectors/commit/20a049381f043dc295ce22434483c0ab28c5a672))
* **deps:** bump anyio from 4.15.1 to 4.16.0 ([#1458](https://github.com/Unique-AG/connectors/issues/1458)) ([2b73dd3](https://github.com/Unique-AG/connectors/commit/2b73dd33d14cf060ab83a3460e29ecd23d6dc563))
* **deps:** bump authlib from 1.9.1 to 1.9.2 ([#1472](https://github.com/Unique-AG/connectors/issues/1472)) ([4643f78](https://github.com/Unique-AG/connectors/commit/4643f78a9015c7e90937357387c3644b3361a05f))
* **deps:** bump dnspython from 2.9.0 to 2.9.1 ([#1420](https://github.com/Unique-AG/connectors/issues/1420)) ([34b87f1](https://github.com/Unique-AG/connectors/commit/34b87f1602afb436aa18a969a61b8e4b74c8fdd8))
* **deps:** bump fastmcp packages ([#1469](https://github.com/Unique-AG/connectors/issues/1469)) ([87007fa](https://github.com/Unique-AG/connectors/commit/87007fa84170bfd31d4840de0054648ebbb4af04))
* **deps:** bump filelock from 4.2.4 to 4.2.6 ([#1432](https://github.com/Unique-AG/connectors/issues/1432)) ([423b016](https://github.com/Unique-AG/connectors/commit/423b016032642b4fce30e67ca470d297c5eb6d67))
* **deps:** bump hf-xet from 1.7.0 to 1.8.0 ([#1422](https://github.com/Unique-AG/connectors/issues/1422)) ([09715f3](https://github.com/Unique-AG/connectors/commit/09715f3d7a61b8f70b4eb5de6e52679cefbc1de6))
* **deps:** bump opentelemetry packages ([#1397](https://github.com/Unique-AG/connectors/issues/1397)) ([c21a413](https://github.com/Unique-AG/connectors/commit/c21a41371d79e6297883de2a261e031b5ad93159))
* **deps:** bump platformdirs from 4.13.7 to 4.14.3 ([#1464](https://github.com/Unique-AG/connectors/issues/1464)) ([cdbdc5a](https://github.com/Unique-AG/connectors/commit/cdbdc5a7db6193e9f5be8752043a2e01270b36bb))
* **deps:** bump pydantic packages ([#1453](https://github.com/Unique-AG/connectors/issues/1453)) ([34b557d](https://github.com/Unique-AG/connectors/commit/34b557d1e2ab15c11b8352b2e53742be333cf147))
* **deps:** bump pydantic-settings from 2.16.1 to 2.16.2 ([#1399](https://github.com/Unique-AG/connectors/issues/1399)) ([934dbf8](https://github.com/Unique-AG/connectors/commit/934dbf81de0c317803914e8925181f0198ad38f7))
* **deps:** bump pytest-asyncio from 1.4.1 to 1.4.1.post1 ([#1470](https://github.com/Unique-AG/connectors/issues/1470)) ([60b236e](https://github.com/Unique-AG/connectors/commit/60b236e3aa2bf21a0be755b13a37b9869ce415ed))
* **deps:** bump python-dateutil from 3.0.0 to 4.0.0 ([#1459](https://github.com/Unique-AG/connectors/issues/1459)) ([1909edc](https://github.com/Unique-AG/connectors/commit/1909edca26a0c7ad2818339e934ead5aee0ea73c))
* **deps:** bump python-multipart from 0.0.32 to 0.0.33 ([#1425](https://github.com/Unique-AG/connectors/issues/1425)) ([d7f3c58](https://github.com/Unique-AG/connectors/commit/d7f3c582cf0e4dc891ebd0857a7a436af2eca1da))
* **deps:** bump pytz from 2026.5 to 2026.6 ([#1426](https://github.com/Unique-AG/connectors/issues/1426)) ([6e819df](https://github.com/Unique-AG/connectors/commit/6e819df259f21bcee0416a1b847bf4da335694f8))
* **deps:** bump websockets from 17.3 to 17.4 ([#1428](https://github.com/Unique-AG/connectors/issues/1428)) ([2781cd5](https://github.com/Unique-AG/connectors/commit/2781cd5e512f40f900442bdffda2c5c029b4a1ef))
* **deps:** bump wrapt from 2.5.1 to 2.5.2 ([#1429](https://github.com/Unique-AG/connectors/issues/1429)) ([3d2d6de](https://github.com/Unique-AG/connectors/commit/3d2d6dec00baa79a1d87c5a1e38317b7ccf94ad3))
* **main:** refresh dependencies and drop unneeded overrides ([#1322](https://github.com/Unique-AG/connectors/issues/1322)) ([a4f2390](https://github.com/Unique-AG/connectors/commit/a4f239000fc35b5809f6c7b50c920ac3c8419ef9))

## [0.2.0](https://github.com/Unique-AG/connectors/compare/with-intelligence-mcp@0.1.1...with-intelligence-mcp@0.2.0) (2026-10-23)


### ⚠ BREAKING CHANGES

* **backstop-mcp,with-intelligence-mcp:** verify database certificates against the CloudNativePG CA ([#1219](https://github.com/Unique-AG/connectors/issues/1219))

### Features

* **backstop-mcp,deps,main,with-intelligence-mcp:** install agent skills after pull ([#1182](https://github.com/Unique-AG/connectors/issues/1182)) ([a8f0104](https://github.com/Unique-AG/connectors/commit/a8f0104bb541182a6e94fa86fc4cec027e7bcf9c))


### Bug Fixes

* **backstop-mcp,kb-mcp,office-365-mcp,with-intelligence-mcp,exp-kyckr-mcp,exp-tiingo-mcp,mcp-credential-auth:** drop compromised eMudhra CA roots ([#1268](https://github.com/Unique-AG/connectors/issues/1268)) ([1f81406](https://github.com/Unique-AG/connectors/commit/1f814060865c9af03a60957b8a57242d9f08d422))
* **backstop-mcp,with-intelligence-mcp:** verify database certificates against the CloudNativePG CA ([#1219](https://github.com/Unique-AG/connectors/issues/1219)) ([4f26e36](https://github.com/Unique-AG/connectors/commit/4f26e36e8e96a9770c9f17d29e61a193928c4ed6))
* **with-intelligence-mcp:** raise memory above the steady working set ([#1196](https://github.com/Unique-AG/connectors/issues/1196)) ([0e77bc0](https://github.com/Unique-AG/connectors/commit/0e77bc0ad2a376bd7abb125c7d8c19963e181ad8))


### Dependencies

* bump asyncpg in /* ([#1240](https://github.com/Unique-AG/connectors/issues/1240)) ([23628b0](https://github.com/Unique-AG/connectors/commit/23628b0de199bbf5ff4f60d8c27c112c68c3d28c))
* bump basedpyright in /* ([#1192](https://github.com/Unique-AG/connectors/issues/1192)) ([5c0cf09](https://github.com/Unique-AG/connectors/commit/5c0cf0965c6d476057e2f63373b753385b81d218))
* bump cryptography in /* ([#1189](https://github.com/Unique-AG/connectors/issues/1189)) ([b2f3689](https://github.com/Unique-AG/connectors/commit/b2f3689c6f4c342bc2e05b4795bf9f552196e572))
* bump fastmcp in /* ([#1198](https://github.com/Unique-AG/connectors/issues/1198)) ([9108152](https://github.com/Unique-AG/connectors/commit/9108152e00405dcb49e1ccf4d17a703a7e4acb79))
* bump mcp in /* ([#1191](https://github.com/Unique-AG/connectors/issues/1191)) ([576fcad](https://github.com/Unique-AG/connectors/commit/576fcad8912cef078f6241f78d13620377e0d159))
* bump python in /services/*/deploy ([#1229](https://github.com/Unique-AG/connectors/issues/1229)) ([c5e1f49](https://github.com/Unique-AG/connectors/commit/c5e1f49ff2c9fce8ef01561463d193b6f627c81b))
* bump ruff in /* ([#1193](https://github.com/Unique-AG/connectors/issues/1193)) ([ac0d4c2](https://github.com/Unique-AG/connectors/commit/ac0d4c21318fe86aec8317a8215fd823250f6fe7))
* bump ruff in /packages/* ([#1241](https://github.com/Unique-AG/connectors/issues/1241)) ([fe61f41](https://github.com/Unique-AG/connectors/commit/fe61f410134445384ce6f5de5ed25edbb249c34e))
* bump sqlalchemy[asyncio] in /services/* ([#1239](https://github.com/Unique-AG/connectors/issues/1239)) ([25d653e](https://github.com/Unique-AG/connectors/commit/25d653e7dd014bd964bc4fc043585e70b9d5599f))
* bump uvicorn[standard] in /services/* ([#1242](https://github.com/Unique-AG/connectors/issues/1242)) ([28f9743](https://github.com/Unique-AG/connectors/commit/28f9743dfa4dbdcc6d9c57a7e09cd432f7d0036f))
* **deps:** move pinned vulnerable dependencies to patched versions ([#1200](https://github.com/Unique-AG/connectors/issues/1200)) ([531d6e0](https://github.com/Unique-AG/connectors/commit/531d6e0d8625cd25014ea8b056475f550af27902))
* **deps:** refresh all transitive dependencies ([#1201](https://github.com/Unique-AG/connectors/issues/1201)) ([68a747d](https://github.com/Unique-AG/connectors/commit/68a747dc8df80f05ba8a5dc5a5caacf111af446f))

## [0.1.1](https://github.com/Unique-AG/connectors/compare/with-intelligence-mcp@0.1.0...with-intelligence-mcp@0.1.1) (2026-10-09)


### Features

* **with-intelligence-mcp:** add the remaining WI tools ([#1153](https://github.com/Unique-AG/connectors/issues/1153)) ([e980460](https://github.com/Unique-AG/connectors/commit/e98046065d1807cda6094a5134892664a0beaf8e))


### Bug Fixes

* **with-intelligence-mcp:** block metrics without gateway JWT ([#1157](https://github.com/Unique-AG/connectors/issues/1157)) ([046e55c](https://github.com/Unique-AG/connectors/commit/046e55c6e516904a0111d35408da30f4944bc9ac))


### Dependencies

* bump fastmcp in /* ([#1144](https://github.com/Unique-AG/connectors/issues/1144)) ([10ce668](https://github.com/Unique-AG/connectors/commit/10ce668ea5ff78da123896db216975cc4f60b513))
* bump mako from 1.4.1 to 1.4.2 in /services/with-intelligence-mcp ([#1166](https://github.com/Unique-AG/connectors/issues/1166)) ([5b3f2ec](https://github.com/Unique-AG/connectors/commit/5b3f2ec47b45fbcbb3c54c999ccc55cdb2853935))
* bump multidict from 6.7.1 to 6.9.1 in /services/with-intelligence-mcp ([#1176](https://github.com/Unique-AG/connectors/issues/1176)) ([dea1921](https://github.com/Unique-AG/connectors/commit/dea19216db7a72afc0ea1d4368dc53b8626c358a))
* bump python in /services/*/deploy ([#1140](https://github.com/Unique-AG/connectors/issues/1140)) ([ecc36dc](https://github.com/Unique-AG/connectors/commit/ecc36dc232dfbfbaba7dd093cf2aa587cacb2297))
* bump ruff in /* ([#1151](https://github.com/Unique-AG/connectors/issues/1151)) ([daf766a](https://github.com/Unique-AG/connectors/commit/daf766a00884e17a13b5277e80a7ce24657212f8))
* bump sqlalchemy[asyncio] in /services/* ([#1148](https://github.com/Unique-AG/connectors/issues/1148)) ([f9632ce](https://github.com/Unique-AG/connectors/commit/f9632cebd8a12fdd0c13e4fc9a3751ffd04f1c34))
* bump starlette in /* ([#1150](https://github.com/Unique-AG/connectors/issues/1150)) ([0ad00a1](https://github.com/Unique-AG/connectors/commit/0ad00a11bba43d2953d7900253b29409eb85b5d6))
* bump urllib3 from 2.7.0 to 2.8.0 in /services/with-intelligence-mcp ([#1138](https://github.com/Unique-AG/connectors/issues/1138)) ([8fe2dbd](https://github.com/Unique-AG/connectors/commit/8fe2dbde07f0d1a6fb1bb2e25d3647e075ccaba8))

## 0.1.0 (2026-09-30)


### Features

* **backstop-mcp,ci,mcp-credential-auth,with-intelligence-mcp:** add OAuth and WI sessions ([#986](https://github.com/Unique-AG/connectors/issues/986)) ([ef85dca](https://github.com/Unique-AG/connectors/commit/ef85dcaa9acb3cd18b989552756984b4c53af8da))
* **with-intelligence-mcp,ci:** scaffold the WI service ([#984](https://github.com/Unique-AG/connectors/issues/984)) ([1b5d638](https://github.com/Unique-AG/connectors/commit/1b5d638b72da7834232967c85aedd181680ddba7))
* **with-intelligence-mcp:** add the WI HTTP client ([#985](https://github.com/Unique-AG/connectors/issues/985)) ([d7ee134](https://github.com/Unique-AG/connectors/commit/d7ee134cdc8d92856d37ed8d85be75a38cf5f780))
* **with-intelligence-mcp:** add WI intelligence tools ([#987](https://github.com/Unique-AG/connectors/issues/987)) ([06721ba](https://github.com/Unique-AG/connectors/commit/06721baf668fd2140f1118a06365345e3873adfd))


### Dependencies

* bump alembic in /services/with-intelligence-mcp ([#1046](https://github.com/Unique-AG/connectors/issues/1046)) ([5f0a1d6](https://github.com/Unique-AG/connectors/commit/5f0a1d6fb0063f5821c575246e76e99ba65a9da0))
* bump basedpyright in /packages/mcp-credential-auth ([#1026](https://github.com/Unique-AG/connectors/issues/1026)) ([61f0ddd](https://github.com/Unique-AG/connectors/commit/61f0dddee8a171e7d8f0398c5f23ada73f7a8b2f))
* bump fastmcp in /* ([#1102](https://github.com/Unique-AG/connectors/issues/1102)) ([1cf61e2](https://github.com/Unique-AG/connectors/commit/1cf61e2c3cd7b0258e82f4be391cafca1f742bab))
* bump hatchling in /* ([#1108](https://github.com/Unique-AG/connectors/issues/1108)) ([776e037](https://github.com/Unique-AG/connectors/commit/776e037be020704fb437c471c548c16db863c2fc))
* bump mcp in /services/with-intelligence-mcp ([#1044](https://github.com/Unique-AG/connectors/issues/1044)) ([e70af1b](https://github.com/Unique-AG/connectors/commit/e70af1b2ea1afa3e9555da14a9d305844409be2d))
* bump ruff in /* ([#1107](https://github.com/Unique-AG/connectors/issues/1107)) ([9953c11](https://github.com/Unique-AG/connectors/commit/9953c118eeac82f79cd1eacc6038f8a35bc2569c))
* bump ruff in /packages/mcp-credential-auth ([#1028](https://github.com/Unique-AG/connectors/issues/1028)) ([bb44f5a](https://github.com/Unique-AG/connectors/commit/bb44f5a5fce11f7022bb67d12f647a25336dddb4))
* bump sqlalchemy[asyncio] in /services/* ([#1105](https://github.com/Unique-AG/connectors/issues/1105)) ([2a55838](https://github.com/Unique-AG/connectors/commit/2a55838cf09455dc9cf769bf6714f393e284dd41))
* bump sqlalchemy[asyncio] in /services/backstop-mcp ([#1066](https://github.com/Unique-AG/connectors/issues/1066)) ([298cff0](https://github.com/Unique-AG/connectors/commit/298cff01b18b4b175b186a70f9e8993e627c0446))
* bump starlette in /services/with-intelligence-mcp ([#1045](https://github.com/Unique-AG/connectors/issues/1045)) ([9fc940d](https://github.com/Unique-AG/connectors/commit/9fc940def0140ff0da63ac5187d6ae8292367261))
* bump unique-mcp in /services/with-intelligence-mcp ([#1068](https://github.com/Unique-AG/connectors/issues/1068)) ([2d2e423](https://github.com/Unique-AG/connectors/commit/2d2e4239afb2c08fce33de5ed9b684d877560828))
* bump uvicorn[standard] in /services/* ([#1067](https://github.com/Unique-AG/connectors/issues/1067)) ([3b93279](https://github.com/Unique-AG/connectors/commit/3b93279c15e729feb9c62ce807134fd762f86432))
* pin lxml to 6.1.3, bump kiota ([#1050](https://github.com/Unique-AG/connectors/issues/1050)) ([122c820](https://github.com/Unique-AG/connectors/commit/122c820f8a4a0e150318d4c58c587bd4cd0b8919))
* **with-intelligence-mcp,backstop-mcp,hello-mcp,kb-mcp,office-365-mcp,ci,scripts,deps:** add deployment and release ([#988](https://github.com/Unique-AG/connectors/issues/988)) ([55f48cd](https://github.com/Unique-AG/connectors/commit/55f48cd2e2676601c5f3d6590a8990c6986c5132))
