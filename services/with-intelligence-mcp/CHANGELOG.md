# Changelog

## [0.2.1](https://github.com/Unique-AG/connectors/compare/with-intelligence-mcp@0.2.0...with-intelligence-mcp@0.2.1) (2026-10-30)


### Bug Fixes

* **architecture-demo-mcp,backstop-mcp,confluence-connector,hello-mcp,kb-mcp,main,mcp-scaffold,office-365-mcp,outlook-semantic-mcp,sharepoint-connector,teams-mcp,with-intelligence-mcp:** run migrations as argo cd sync hooks after the database ([#1360](https://github.com/Unique-AG/connectors/issues/1360)) ([5264f9f](https://github.com/Unique-AG/connectors/commit/5264f9f14505bbc57d01fe676946daaf63e261f3))
* **architecture-demo-mcp,backstop-mcp,confluence-connector,hello-mcp,kb-mcp,office-365-mcp,outlook-semantic-mcp,sharepoint-connector,teams-mcp,with-intelligence-mcp:** bump base chart for network policy sync-wave ordering ([#1307](https://github.com/Unique-AG/connectors/issues/1307)) ([8e9eba5](https://github.com/Unique-AG/connectors/commit/8e9eba588c9052ef87a356a0bd9c575170848ca2))
* **main:** vulna squash MAJOR VERSION BUMP pillow 12.3.0 to 13.0.0 ([#1296](https://github.com/Unique-AG/connectors/issues/1296)) ([1704f7c](https://github.com/Unique-AG/connectors/commit/1704f7c9a36082c6deff1615b1dfbf3a55b48ac0))


### Dependencies

* **architecture-demo-mcp,backstop-mcp,ci,exp-kyckr-mcp,exp-tiingo-mcp,hello-mcp,kb-mcp,mcp-openapi,mcp-scaffold,office-365-mcp,with-intelligence-mcp:** pin one version of each shared dependency ([#1291](https://github.com/Unique-AG/connectors/issues/1291)) ([a5cfdb8](https://github.com/Unique-AG/connectors/commit/a5cfdb8fc888e64a212fdf6dbe0457a453737ccf))
* **architecture-demo-mcp,backstop-mcp,exp-kyckr-mcp,exp-tiingo-mcp,hello-mcp,kb-mcp,main,mcp-configs,mcp-credential-auth,mcp-observability,mcp-openapi,mcp-scaffold,office-365-mcp,with-intelligence-mcp:** give every Python project the same poe tasks ([#1292](https://github.com/Unique-AG/connectors/issues/1292)) ([71547e7](https://github.com/Unique-AG/connectors/commit/71547e7c1f447d8eefe270b076f91129514cd96c))
* **architecture-demo-mcp,backstop-mcp,exp-kyckr-mcp,exp-tiingo-mcp,hello-mcp,kb-mcp,mcp-architecture,mcp-configs,mcp-credential-auth,mcp-observability,mcp-openapi,mcp-scaffold,office-365-mcp,with-intelligence-mcp:** require Python 3.14 and resolve one version of every package in every lock ([#1293](https://github.com/Unique-AG/connectors/issues/1293)) ([8f0a04b](https://github.com/Unique-AG/connectors/commit/8f0a04b87a2c33a0b0cb191dbee7f74286b2d1f1))
* bump pillow from 12.3.0 to 13.0.0 in /services/with-intelligence-mcp ([#1271](https://github.com/Unique-AG/connectors/issues/1271)) ([a2a5f19](https://github.com/Unique-AG/connectors/commit/a2a5f1909407fa1b26b239bcf640b443cb654b9d))
* bump sqlalchemy[asyncio] in /services/backstop-mcp ([#1279](https://github.com/Unique-AG/connectors/issues/1279)) ([20a0493](https://github.com/Unique-AG/connectors/commit/20a049381f043dc295ce22434483c0ab28c5a672))
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
