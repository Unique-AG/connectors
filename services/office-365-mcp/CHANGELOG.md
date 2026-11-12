# Changelog

## [0.4.0](https://github.com/Unique-AG/connectors/compare/office-365-mcp@0.3.3...office-365-mcp@0.4.0) (2026-11-12)


### ⚠ BREAKING CHANGES

* **mcp-oauth,teams-mcp,outlook-semantic-mcp,office-365-mcp:** reject sign-ins from Entra tenants not on the allowlist ([#1357](https://github.com/Unique-AG/connectors/issues/1357))

### Features

* **backstop-mcp,kb-mcp,office-365-mcp,outlook-semantic-mcp,teams-mcp,with-intelligence-mcp:** advertise the new server icon in serverInfo ([#1377](https://github.com/Unique-AG/connectors/issues/1377)) ([19e8a00](https://github.com/Unique-AG/connectors/commit/19e8a009ff76826a0d606c241197cea432cfcebe))
* **ci,main:** gate releases, scan images nightly, and update dependencies nightly ([#1305](https://github.com/Unique-AG/connectors/issues/1305)) ([b3b274c](https://github.com/Unique-AG/connectors/commit/b3b274cf0ab3cecc3a1dece3eff5c116d24d9418))
* **mcp-server-module,mcp-observability:** rate-limit MCP tool calls per user ([#1358](https://github.com/Unique-AG/connectors/issues/1358)) ([bbe4bc0](https://github.com/Unique-AG/connectors/commit/bbe4bc07bde6b67cecee762e25a16cfeac6cc67a))
* **mcp-server-module,office-365-mcp,with-intelligence-mcp,kb-mcp:** log one audit line per MCP tool call ([#1354](https://github.com/Unique-AG/connectors/issues/1354)) ([eb7de3b](https://github.com/Unique-AG/connectors/commit/eb7de3b7c06feba5f9445e68198ba8d8fa0cf4fb))
* **office-365-mcp,recordings-and-transcripts:** support Teams call transcripts ([#1463](https://github.com/Unique-AG/connectors/issues/1463)) ([16a9dce](https://github.com/Unique-AG/connectors/commit/16a9dce4a7d4e553b4b56fafa95c33ffd6ca7d7e))
* **office-365-mcp:** add SharePoint lists support ([#1527](https://github.com/Unique-AG/connectors/issues/1527)) ([3fd3972](https://github.com/Unique-AG/connectors/commit/3fd397256d8d9f1c220d9e6fab5cafed893290a0))
* **office-365-mcp:** align the tools and docs to the use cases ([#1577](https://github.com/Unique-AG/connectors/issues/1577)) ([cc156e4](https://github.com/Unique-AG/connectors/commit/cc156e48e1d76c1ffb552fd2474cd0018b3f96f3))
* **office-365-mcp:** take a list of presets in the Terraform input and the chart ([#1359](https://github.com/Unique-AG/connectors/issues/1359)) ([db1b3f6](https://github.com/Unique-AG/connectors/commit/db1b3f68b4d4a44482ddbd43a083d4c6025ced82))
* **office-365-mcp:** take Markdown for Teams, mail, and event bodies ([#1287](https://github.com/Unique-AG/connectors/issues/1287)) ([8f6bee2](https://github.com/Unique-AG/connectors/commit/8f6bee233fff4521cee8feabd1731d4632d8f33a))


### Bug Fixes

* **architecture-demo-mcp,backstop-mcp,confluence-connector,hello-mcp,kb-mcp,main,mcp-scaffold,office-365-mcp,outlook-semantic-mcp,sharepoint-connector,teams-mcp,with-intelligence-mcp:** run migrations as argo cd sync hooks after the database ([#1360](https://github.com/Unique-AG/connectors/issues/1360)) ([5264f9f](https://github.com/Unique-AG/connectors/commit/5264f9f14505bbc57d01fe676946daaf63e261f3))
* **architecture-demo-mcp,backstop-mcp,confluence-connector,hello-mcp,kb-mcp,office-365-mcp,outlook-semantic-mcp,sharepoint-connector,teams-mcp,with-intelligence-mcp:** bump base chart for network policy sync-wave ordering ([#1307](https://github.com/Unique-AG/connectors/issues/1307)) ([8e9eba5](https://github.com/Unique-AG/connectors/commit/8e9eba588c9052ef87a356a0bd9c575170848ca2))
* **backstop-mcp,with-intelligence-mcp,kb-mcp,office-365-mcp:** mask unexpected tool error details ([#1344](https://github.com/Unique-AG/connectors/issues/1344)) ([5144918](https://github.com/Unique-AG/connectors/commit/5144918b0f113a024e7e19237832a315d97febce))
* deny egress to RFC1918 and link-local ranges in every MCP chart ([#1353](https://github.com/Unique-AG/connectors/issues/1353)) ([5949e66](https://github.com/Unique-AG/connectors/commit/5949e6698615dfd7de48116cd09c0550467485f1))
* **main:** vulna squash MAJOR VERSION BUMP pillow 12.3.0 to 13.0.0 ([#1296](https://github.com/Unique-AG/connectors/issues/1296)) ([1704f7c](https://github.com/Unique-AG/connectors/commit/1704f7c9a36082c6deff1615b1dfbf3a55b48ac0))
* **mcp-oauth,teams-mcp,outlook-semantic-mcp,office-365-mcp:** reject sign-ins from Entra tenants not on the allowlist ([#1357](https://github.com/Unique-AG/connectors/issues/1357)) ([4cc5936](https://github.com/Unique-AG/connectors/commit/4cc5936fda54b507ab3183ef0f2c7e6dec109abc))
* **office-365-mcp:** add a native Teams meeting to an event with attendees by default ([#1597](https://github.com/Unique-AG/connectors/issues/1597)) ([a868fbb](https://github.com/Unique-AG/connectors/commit/a868fbbc3ac0c99da87f6d2bd6ce73929261d2ec))
* **office-365-mcp:** fix server bugs found by the use-case recordings ([#1528](https://github.com/Unique-AG/connectors/issues/1528)) ([e30b24a](https://github.com/Unique-AG/connectors/commit/e30b24aaab989e59d8d0cd74f0fef6bea4c29eda))
* **office-365-mcp:** keep the quoted thread in a reply or forward draft ([#1598](https://github.com/Unique-AG/connectors/issues/1598)) ([b696219](https://github.com/Unique-AG/connectors/commit/b696219c878b9446e20bfd89843becfcccfe4ca3))
* **office-365-mcp:** prefix each tool title with its Microsoft 365 service ([#1627](https://github.com/Unique-AG/connectors/issues/1627)) ([e60d9c4](https://github.com/Unique-AG/connectors/commit/e60d9c4beecadda69906a272907d8d65f100d16f))
* **office-365-mcp:** search a domain recipient in every address field ([#1579](https://github.com/Unique-AG/connectors/issues/1579)) ([54f58cb](https://github.com/Unique-AG/connectors/commit/54f58cb1b30f56cd51a7569e6902c25cf23e43f4))


### Dependencies

* **architecture-demo-mcp,backstop-mcp,ci,exp-kyckr-mcp,exp-tiingo-mcp,hello-mcp,kb-mcp,mcp-openapi,mcp-scaffold,office-365-mcp,with-intelligence-mcp:** pin one version of each shared dependency ([#1291](https://github.com/Unique-AG/connectors/issues/1291)) ([a5cfdb8](https://github.com/Unique-AG/connectors/commit/a5cfdb8fc888e64a212fdf6dbe0457a453737ccf))
* **architecture-demo-mcp,backstop-mcp,exp-kyckr-mcp,exp-tiingo-mcp,hello-mcp,kb-mcp,main,mcp-configs,mcp-credential-auth,mcp-observability,mcp-openapi,mcp-scaffold,office-365-mcp,with-intelligence-mcp:** give every Python project the same poe tasks ([#1292](https://github.com/Unique-AG/connectors/issues/1292)) ([71547e7](https://github.com/Unique-AG/connectors/commit/71547e7c1f447d8eefe270b076f91129514cd96c))
* **architecture-demo-mcp,backstop-mcp,exp-kyckr-mcp,exp-tiingo-mcp,hello-mcp,kb-mcp,mcp-architecture,mcp-configs,mcp-credential-auth,mcp-observability,mcp-openapi,mcp-scaffold,office-365-mcp,with-intelligence-mcp:** require Python 3.14 and resolve one version of every package in every lock ([#1293](https://github.com/Unique-AG/connectors/issues/1293)) ([8f0a04b](https://github.com/Unique-AG/connectors/commit/8f0a04b87a2c33a0b0cb191dbee7f74286b2d1f1))
* **deps:** bump anyio from 4.15.1 to 4.16.0 ([#1458](https://github.com/Unique-AG/connectors/issues/1458)) ([2b73dd3](https://github.com/Unique-AG/connectors/commit/2b73dd33d14cf060ab83a3460e29ecd23d6dc563))
* **deps:** bump authlib from 1.9.1 to 1.9.2 ([#1472](https://github.com/Unique-AG/connectors/issues/1472)) ([4643f78](https://github.com/Unique-AG/connectors/commit/4643f78a9015c7e90937357387c3644b3361a05f))
* **deps:** bump authlib from 1.9.1 to 1.9.5 ([#1564](https://github.com/Unique-AG/connectors/issues/1564)) ([970fd93](https://github.com/Unique-AG/connectors/commit/970fd930ee2a9e14a0039158602384dd54772466))
* **deps:** bump azure-identity from 1.26.0 to 1.27.0 ([#1419](https://github.com/Unique-AG/connectors/issues/1419)) ([49e4c39](https://github.com/Unique-AG/connectors/commit/49e4c39527cd1c26b6763a3a0654d7fef84b3919))
* **deps:** bump azurerm from 5.11.0 to 5.12.0 ([#1395](https://github.com/Unique-AG/connectors/issues/1395)) ([582a096](https://github.com/Unique-AG/connectors/commit/582a09693c5656b9b016ea8e42a1317f0fd090de))
* **deps:** bump azurerm from 5.12.0 to 5.13.0 ([#1572](https://github.com/Unique-AG/connectors/issues/1572)) ([697230b](https://github.com/Unique-AG/connectors/commit/697230b664bd3098f2a4902e2ae66c5cc028c478))
* **deps:** bump click from 8.5.0 to 8.5.1 ([#1594](https://github.com/Unique-AG/connectors/issues/1594)) ([6b63621](https://github.com/Unique-AG/connectors/commit/6b636210023b5042d1431856495d42ea4e41bfac))
* **deps:** bump cyclopts from 5.2.0 to 5.3.3 ([#1509](https://github.com/Unique-AG/connectors/issues/1509)) ([2e82f58](https://github.com/Unique-AG/connectors/commit/2e82f58d7147237e1fe5d76884ca42b104097322))
* **deps:** bump cyclopts from 5.3.3 to 5.4.0 ([#1640](https://github.com/Unique-AG/connectors/issues/1640)) ([fb15e80](https://github.com/Unique-AG/connectors/commit/fb15e80557f0e19c6dfbcdaece0075f225f0b370))
* **deps:** bump dnspython from 2.9.0 to 2.9.1 ([#1420](https://github.com/Unique-AG/connectors/issues/1420)) ([34b87f1](https://github.com/Unique-AG/connectors/commit/34b87f1602afb436aa18a969a61b8e4b74c8fdd8))
* **deps:** bump dnspython from 2.9.0 to 2.9.2 ([#1533](https://github.com/Unique-AG/connectors/issues/1533)) ([a7972c0](https://github.com/Unique-AG/connectors/commit/a7972c0eae54fc0dbcb801dc61b39b02c55e1998))
* **deps:** bump fastmcp packages ([#1469](https://github.com/Unique-AG/connectors/issues/1469)) ([87007fa](https://github.com/Unique-AG/connectors/commit/87007fa84170bfd31d4840de0054648ebbb4af04))
* **deps:** bump fastmcp packages ([#1530](https://github.com/Unique-AG/connectors/issues/1530)) ([eee2af2](https://github.com/Unique-AG/connectors/commit/eee2af2eb2ff4943ac89016ac463f86c192c5a67))
* **deps:** bump filelock from 4.2.4 to 4.2.6 ([#1432](https://github.com/Unique-AG/connectors/issues/1432)) ([423b016](https://github.com/Unique-AG/connectors/commit/423b016032642b4fce30e67ca470d297c5eb6d67))
* **deps:** bump filelock from 4.2.4 to 4.2.9 ([#1547](https://github.com/Unique-AG/connectors/issues/1547)) ([e5e9b82](https://github.com/Unique-AG/connectors/commit/e5e9b82d43fa25487ff00cbbb609c8091ef107de))
* **deps:** bump hf-xet from 1.7.0 to 1.8.0 ([#1422](https://github.com/Unique-AG/connectors/issues/1422)) ([09715f3](https://github.com/Unique-AG/connectors/commit/09715f3d7a61b8f70b4eb5de6e52679cefbc1de6))
* **deps:** bump jiter from 0.17.0 to 0.19.0 ([#1589](https://github.com/Unique-AG/connectors/issues/1589)) ([7e02e08](https://github.com/Unique-AG/connectors/commit/7e02e08611f18bc9cb6cfd2d2bc34075041b10d1))
* **deps:** bump joserfc from 1.7.7 to 1.8.0 ([#1538](https://github.com/Unique-AG/connectors/issues/1538)) ([70bf11d](https://github.com/Unique-AG/connectors/commit/70bf11d7a2115d25496f8c56e8344296e1da7d02))
* **deps:** bump microsoft-kiota packages ([#1590](https://github.com/Unique-AG/connectors/issues/1590)) ([fe1f729](https://github.com/Unique-AG/connectors/commit/fe1f729d3ff873e7cd961f2993518941e8e943b4))
* **deps:** bump msgraph-sdk from 1.62.0 to 1.65.0 ([#1396](https://github.com/Unique-AG/connectors/issues/1396)) ([21a0950](https://github.com/Unique-AG/connectors/commit/21a09505c3f40ac1a648404815b2a97be4d0ad0d))
* **deps:** bump opentelemetry packages ([#1397](https://github.com/Unique-AG/connectors/issues/1397)) ([c21a413](https://github.com/Unique-AG/connectors/commit/c21a41371d79e6297883de2a261e031b5ad93159))
* **deps:** bump platformdirs from 4.13.5 to 4.14.5 ([#1548](https://github.com/Unique-AG/connectors/issues/1548)) ([1afb94c](https://github.com/Unique-AG/connectors/commit/1afb94c03fd6fb2c3a5b86a07a4ebdc7351ae096))
* **deps:** bump platformdirs from 4.13.7 to 4.14.3 ([#1464](https://github.com/Unique-AG/connectors/issues/1464)) ([cdbdc5a](https://github.com/Unique-AG/connectors/commit/cdbdc5a7db6193e9f5be8752043a2e01270b36bb))
* **deps:** bump pydantic packages ([#1453](https://github.com/Unique-AG/connectors/issues/1453)) ([34b557d](https://github.com/Unique-AG/connectors/commit/34b557d1e2ab15c11b8352b2e53742be333cf147))
* **deps:** bump pydantic packages ([#1563](https://github.com/Unique-AG/connectors/issues/1563)) ([53901f0](https://github.com/Unique-AG/connectors/commit/53901f05119b7baf41e3936a84dfdeb4f4c04808))
* **deps:** bump pydantic-settings from 2.16.1 to 2.16.2 ([#1399](https://github.com/Unique-AG/connectors/issues/1399)) ([934dbf8](https://github.com/Unique-AG/connectors/commit/934dbf81de0c317803914e8925181f0198ad38f7))
* **deps:** bump pytest-asyncio from 1.4.1 to 1.4.1.post1 ([#1470](https://github.com/Unique-AG/connectors/issues/1470)) ([60b236e](https://github.com/Unique-AG/connectors/commit/60b236e3aa2bf21a0be755b13a37b9869ce415ed))
* **deps:** bump python-dateutil from 3.0.0 to 4.0.0 ([#1459](https://github.com/Unique-AG/connectors/issues/1459)) ([1909edc](https://github.com/Unique-AG/connectors/commit/1909edca26a0c7ad2818339e934ead5aee0ea73c))
* **deps:** bump python-multipart from 0.0.32 to 0.0.33 ([#1425](https://github.com/Unique-AG/connectors/issues/1425)) ([d7f3c58](https://github.com/Unique-AG/connectors/commit/d7f3c582cf0e4dc891ebd0857a7a436af2eca1da))
* **deps:** bump pytz from 2026.5 to 2026.6 ([#1426](https://github.com/Unique-AG/connectors/issues/1426)) ([6e819df](https://github.com/Unique-AG/connectors/commit/6e819df259f21bcee0416a1b847bf4da335694f8))
* **deps:** bump regex from 2026.11.7 to 2026.11.9 ([#1641](https://github.com/Unique-AG/connectors/issues/1641)) ([eb9ed19](https://github.com/Unique-AG/connectors/commit/eb9ed19fb498191a20c530d1beb178244565a85a))
* **deps:** bump regex from 2026.9.29 to 2026.11.7 ([#1596](https://github.com/Unique-AG/connectors/issues/1596)) ([2438875](https://github.com/Unique-AG/connectors/commit/2438875c516222430e8849996f4f17f5099a014c))
* **deps:** bump ruff from 0.17.3 to 0.17.4 ([#1573](https://github.com/Unique-AG/connectors/issues/1573)) ([7aad996](https://github.com/Unique-AG/connectors/commit/7aad99614439067376d84c4b79c0085a5a213b25))
* **deps:** bump sse-starlette from 3.5.0 to 3.7.0 ([#1601](https://github.com/Unique-AG/connectors/issues/1601)) ([0205d12](https://github.com/Unique-AG/connectors/commit/0205d12bd183e60b7655137546e9f7482c747226))
* **deps:** bump std-uritemplate from 2.0.12 to 2.0.13 ([#1427](https://github.com/Unique-AG/connectors/issues/1427)) ([616529b](https://github.com/Unique-AG/connectors/commit/616529b3a8e537c8349a1b8691a9df1b2b1de6db))
* **deps:** bump typing-inspection from 0.4.4 to 0.4.5 ([#1561](https://github.com/Unique-AG/connectors/issues/1561)) ([b5ba8b6](https://github.com/Unique-AG/connectors/commit/b5ba8b6a22630bdf68c55628c3ab5d3c8e258140))
* **deps:** bump uncalled-for from 0.4.1 to 0.6.0 ([#1565](https://github.com/Unique-AG/connectors/issues/1565)) ([952417d](https://github.com/Unique-AG/connectors/commit/952417dd3595afbc4e4d73f893b7fa675775c936))
* **deps:** bump unique packages ([#1585](https://github.com/Unique-AG/connectors/issues/1585)) ([bfeb189](https://github.com/Unique-AG/connectors/commit/bfeb189616648042eade65dcce8f4d6f5ae12c42))
* **deps:** bump websockets from 17.3 to 17.4 ([#1428](https://github.com/Unique-AG/connectors/issues/1428)) ([2781cd5](https://github.com/Unique-AG/connectors/commit/2781cd5e512f40f900442bdffda2c5c029b4a1ef))
* **deps:** bump wrapt from 2.5.1 to 2.5.2 ([#1429](https://github.com/Unique-AG/connectors/issues/1429)) ([3d2d6de](https://github.com/Unique-AG/connectors/commit/3d2d6dec00baa79a1d87c5a1e38317b7ccf94ad3))
* **main:** align the python base image digest in every Dockerfile ([#1628](https://github.com/Unique-AG/connectors/issues/1628)) ([39e8acc](https://github.com/Unique-AG/connectors/commit/39e8accc2659fc07af97f2c23ea5910d984dcb7b))
* **main:** refresh dependencies and drop unneeded overrides ([#1322](https://github.com/Unique-AG/connectors/issues/1322)) ([a4f2390](https://github.com/Unique-AG/connectors/commit/a4f239000fc35b5809f6c7b50c920ac3c8419ef9))

## [0.3.3](https://github.com/Unique-AG/connectors/compare/office-365-mcp@0.3.2...office-365-mcp@0.3.3) (2026-10-23)


### Features

* **office-365-mcp:** accept the enabled tools as a YAML list ([#1250](https://github.com/Unique-AG/connectors/issues/1250)) ([0f30be8](https://github.com/Unique-AG/connectors/commit/0f30be8da0200b0c4c0ecb6226f193d7454b6461))


### Bug Fixes

* **backstop-mcp,kb-mcp,office-365-mcp,with-intelligence-mcp,exp-kyckr-mcp,exp-tiingo-mcp,mcp-credential-auth:** drop compromised eMudhra CA roots ([#1268](https://github.com/Unique-AG/connectors/issues/1268)) ([1f81406](https://github.com/Unique-AG/connectors/commit/1f814060865c9af03a60957b8a57242d9f08d422))

## [0.3.2](https://github.com/Unique-AG/connectors/compare/office-365-mcp@0.3.1...office-365-mcp@0.3.2) (2026-10-19)


### Bug Fixes

* **office-365-mcp:** allow several registrations with one display name ([#1248](https://github.com/Unique-AG/connectors/issues/1248)) ([70a36ac](https://github.com/Unique-AG/connectors/commit/70a36aca9936ccdc8fe64f7681af779c49bd1097))

## [0.3.1](https://github.com/Unique-AG/connectors/compare/office-365-mcp@0.3.0...office-365-mcp@0.3.1) (2026-10-19)


### Features

* **office-365-mcp:** add /admin/consent redirect to the admin-consent URL ([#1226](https://github.com/Unique-AG/connectors/issues/1226)) ([fa4948b](https://github.com/Unique-AG/connectors/commit/fa4948bed0d9934462355800826808c4c2ba5d61))
* **office-365-mcp:** select several presets in one deployment ([#1244](https://github.com/Unique-AG/connectors/issues/1244)) ([7923a6e](https://github.com/Unique-AG/connectors/commit/7923a6e8fdc5aa8d6e36b97f11c1afa07f0d4ced))


### Dependencies

* bump asyncpg in /* ([#1240](https://github.com/Unique-AG/connectors/issues/1240)) ([23628b0](https://github.com/Unique-AG/connectors/commit/23628b0de199bbf5ff4f60d8c27c112c68c3d28c))
* bump pydantic in /services/* ([#1238](https://github.com/Unique-AG/connectors/issues/1238)) ([01801d2](https://github.com/Unique-AG/connectors/commit/01801d2b560ef29bdced07bbe1101cc8fd655457))
* bump python in /services/*/deploy ([#1229](https://github.com/Unique-AG/connectors/issues/1229)) ([c5e1f49](https://github.com/Unique-AG/connectors/commit/c5e1f49ff2c9fce8ef01561463d193b6f627c81b))
* bump ruff in /packages/* ([#1241](https://github.com/Unique-AG/connectors/issues/1241)) ([fe61f41](https://github.com/Unique-AG/connectors/commit/fe61f410134445384ce6f5de5ed25edbb249c34e))
* bump uvicorn[standard] in /services/* ([#1242](https://github.com/Unique-AG/connectors/issues/1242)) ([28f9743](https://github.com/Unique-AG/connectors/commit/28f9743dfa4dbdcc6d9c57a7e09cd432f7d0036f))

## [0.3.0](https://github.com/Unique-AG/connectors/compare/office-365-mcp@0.2.4...office-365-mcp@0.3.0) (2026-10-14)


### ⚠ BREAKING CHANGES

* **office-365-mcp:** return Teams message bodies as Microsoft 365 sends them ([#1207](https://github.com/Unique-AG/connectors/issues/1207))
* **office-365-mcp:** always return the SharePoint and OneDrive web address ([#1206](https://github.com/Unique-AG/connectors/issues/1206))
* **office-365-mcp:** extend outlook mail, calendar, rule and folder tools ([#1165](https://github.com/Unique-AG/connectors/issues/1165))
* **office-365-mcp:** reach group and site notebooks in onenote tools ([#1159](https://github.com/Unique-AG/connectors/issues/1159))
* **office-365-mcp:** fix prod tool failures and use one mail handle ([#1173](https://github.com/Unique-AG/connectors/issues/1173))
* **office-365-mcp:** remove limits Graph does not set, confirm writes that reach others ([#1133](https://github.com/Unique-AG/connectors/issues/1133))
* **office-365-mcp:** remove inline attachments from the draft tools ([#1112](https://github.com/Unique-AG/connectors/issues/1112))

### Features

* **office-365-mcp:** add sharepoint and onedrive parameters and tools ([#1155](https://github.com/Unique-AG/connectors/issues/1155)) ([3127429](https://github.com/Unique-AG/connectors/commit/3127429a306de2b0082572cc9486240484f1ab58))
* **office-365-mcp:** add teams parameters and tools ([#1154](https://github.com/Unique-AG/connectors/issues/1154)) ([312a460](https://github.com/Unique-AG/connectors/commit/312a460c32d47a43aa74034d3d79c462b682639d))
* **office-365-mcp:** extend outlook mail, calendar, rule and folder tools ([#1165](https://github.com/Unique-AG/connectors/issues/1165)) ([c30547d](https://github.com/Unique-AG/connectors/commit/c30547d20bcd559b8b45196011ef3a734d9d8865))
* **office-365-mcp:** reach group and site notebooks in onenote tools ([#1159](https://github.com/Unique-AG/connectors/issues/1159)) ([54970a8](https://github.com/Unique-AG/connectors/commit/54970a84745a86899c5e420c62a11f8468e1ccd4))
* **office-365-mcp:** remove limits Graph does not set, confirm writes that reach others ([#1133](https://github.com/Unique-AG/connectors/issues/1133)) ([be428f9](https://github.com/Unique-AG/connectors/commit/be428f96886e5bd4918594ac5a20702c138c3c0e))


### Bug Fixes

* **office-365-mcp:** always return the SharePoint and OneDrive web address ([#1206](https://github.com/Unique-AG/connectors/issues/1206)) ([b26992e](https://github.com/Unique-AG/connectors/commit/b26992eb9d7e8ddbce8b19b2c3c16da1be4f2131))
* **office-365-mcp:** cap sharepoint_read_file while it downloads ([c3f8dc5](https://github.com/Unique-AG/connectors/commit/c3f8dc558fb5235eb3c4627bd9d4db915e9cef23))
* **office-365-mcp:** close idle MCP sessions after a configurable timeout ([#1113](https://github.com/Unique-AG/connectors/issues/1113)) ([02c64ec](https://github.com/Unique-AG/connectors/commit/02c64ecff11e5a7cb3bc4a324e542cfc9c6882f5))
* **office-365-mcp:** cut idle and peak memory after the prod OOM kill ([#1211](https://github.com/Unique-AG/connectors/issues/1211)) ([fedd204](https://github.com/Unique-AG/connectors/commit/fedd204ac1692e4c530035bd8adc9097ef80b27c))
* **office-365-mcp:** fail outlook_mark_mail when no message was marked ([0ad93ad](https://github.com/Unique-AG/connectors/commit/0ad93ad1bc7180123305aaa1a560f4ae854391c2))
* **office-365-mcp:** fix prod tool failures and use one mail handle ([#1173](https://github.com/Unique-AG/connectors/issues/1173)) ([99d3c34](https://github.com/Unique-AG/connectors/commit/99d3c342393ff7171ea78d66dc68b7055d27d684))
* **office-365-mcp:** give the model Graph's reason for a rejected request ([0ad93ad](https://github.com/Unique-AG/connectors/commit/0ad93ad1bc7180123305aaa1a560f4ae854391c2))
* **office-365-mcp:** keep secrets out of configuration errors ([c3f8dc5](https://github.com/Unique-AG/connectors/commit/c3f8dc558fb5235eb3c4627bd9d4db915e9cef23))
* **office-365-mcp:** keep the written-but-not-read answer of OneNote writes ([0ad93ad](https://github.com/Unique-AG/connectors/commit/0ad93ad1bc7180123305aaa1a560f4ae854391c2))
* **office-365-mcp:** make tool descriptions match what the tools do ([0ad93ad](https://github.com/Unique-AG/connectors/commit/0ad93ad1bc7180123305aaa1a560f4ae854391c2))
* **office-365-mcp:** remove inline attachments from the draft tools ([#1112](https://github.com/Unique-AG/connectors/issues/1112)) ([ba01da9](https://github.com/Unique-AG/connectors/commit/ba01da947bb3aa08109c1097cf60a165b38aa255))
* **office-365-mcp:** report a deleted OneNote page when the retried delete finds it gone ([0ad93ad](https://github.com/Unique-AG/connectors/commit/0ad93ad1bc7180123305aaa1a560f4ae854391c2))
* **office-365-mcp:** return Teams message bodies as Microsoft 365 sends them ([#1207](https://github.com/Unique-AG/connectors/issues/1207)) ([a274811](https://github.com/Unique-AG/connectors/commit/a274811fac39b41d975436740e72712137225f85))
* **office-365-mcp:** say why a confirmation question got no answer ([0ad93ad](https://github.com/Unique-AG/connectors/commit/0ad93ad1bc7180123305aaa1a560f4ae854391c2))
* **office-365-mcp:** stop logging outbound request URLs ([c3f8dc5](https://github.com/Unique-AG/connectors/commit/c3f8dc558fb5235eb3c4627bd9d4db915e9cef23))
* **office-365-mcp:** tell the model that a failed write can already be done ([0ad93ad](https://github.com/Unique-AG/connectors/commit/0ad93ad1bc7180123305aaa1a560f4ae854391c2))


### Dependencies

* bump basedpyright in /* ([#1192](https://github.com/Unique-AG/connectors/issues/1192)) ([5c0cf09](https://github.com/Unique-AG/connectors/commit/5c0cf0965c6d476057e2f63373b753385b81d218))
* bump cryptography in /* ([#1189](https://github.com/Unique-AG/connectors/issues/1189)) ([b2f3689](https://github.com/Unique-AG/connectors/commit/b2f3689c6f4c342bc2e05b4795bf9f552196e572))
* bump hatchling in /* ([#1108](https://github.com/Unique-AG/connectors/issues/1108)) ([776e037](https://github.com/Unique-AG/connectors/commit/776e037be020704fb437c471c548c16db863c2fc))
* bump mcp in /* ([#1191](https://github.com/Unique-AG/connectors/issues/1191)) ([576fcad](https://github.com/Unique-AG/connectors/commit/576fcad8912cef078f6241f78d13620377e0d159))
* bump multidict from 6.7.1 to 6.9.1 in /services/office-365-mcp ([#1167](https://github.com/Unique-AG/connectors/issues/1167)) ([aafde4b](https://github.com/Unique-AG/connectors/commit/aafde4b94c8a73b22dba5d37d337047f3f62d2ae))
* bump python in /services/*/deploy ([#1140](https://github.com/Unique-AG/connectors/issues/1140)) ([ecc36dc](https://github.com/Unique-AG/connectors/commit/ecc36dc232dfbfbaba7dd093cf2aa587cacb2297))
* bump ruff in /* ([#1107](https://github.com/Unique-AG/connectors/issues/1107)) ([9953c11](https://github.com/Unique-AG/connectors/commit/9953c118eeac82f79cd1eacc6038f8a35bc2569c))
* bump ruff in /* ([#1151](https://github.com/Unique-AG/connectors/issues/1151)) ([daf766a](https://github.com/Unique-AG/connectors/commit/daf766a00884e17a13b5277e80a7ce24657212f8))
* bump ruff in /* ([#1193](https://github.com/Unique-AG/connectors/issues/1193)) ([ac0d4c2](https://github.com/Unique-AG/connectors/commit/ac0d4c21318fe86aec8317a8215fd823250f6fe7))
* bump starlette in /* ([#1150](https://github.com/Unique-AG/connectors/issues/1150)) ([0ad00a1](https://github.com/Unique-AG/connectors/commit/0ad00a11bba43d2953d7900253b29409eb85b5d6))
* bump unique-mcp in /services/office-365-mcp ([#1109](https://github.com/Unique-AG/connectors/issues/1109)) ([3653a86](https://github.com/Unique-AG/connectors/commit/3653a8604cbf76470b62fb801af44cc4e447f771))
* **deps:** move pinned vulnerable dependencies to patched versions ([#1200](https://github.com/Unique-AG/connectors/issues/1200)) ([531d6e0](https://github.com/Unique-AG/connectors/commit/531d6e0d8625cd25014ea8b056475f550af27902))
* **deps:** refresh all transitive dependencies ([#1201](https://github.com/Unique-AG/connectors/issues/1201)) ([68a747d](https://github.com/Unique-AG/connectors/commit/68a747dc8df80f05ba8a5dc5a5caacf111af446f))
* **with-intelligence-mcp,backstop-mcp,hello-mcp,kb-mcp,office-365-mcp,ci,scripts,deps:** add deployment and release ([#988](https://github.com/Unique-AG/connectors/issues/988)) ([55f48cd](https://github.com/Unique-AG/connectors/commit/55f48cd2e2676601c5f3d6590a8990c6986c5132))

## [0.2.4](https://github.com/Unique-AG/connectors/compare/office-365-mcp@0.2.3...office-365-mcp@0.2.4) (2026-09-25)


### Features

* **office-365-mcp:** add Outlook mailbox, categories, attachments and calendar parity tools ([#1093](https://github.com/Unique-AG/connectors/issues/1093)) ([5e32c50](https://github.com/Unique-AG/connectors/commit/5e32c5098c7eb9147a14c982024a726ecf64cc9a))
* **office-365-mcp:** Teams send tools and teams-write preset ([#1096](https://github.com/Unique-AG/connectors/issues/1096)) ([41a4d31](https://github.com/Unique-AG/connectors/commit/41a4d318a238c3600c1102f2ada61d4eda753fa9))


### Bug Fixes

* **office-365-mcp:** stop publishing a root-level anyOf/oneOf/not in five tool schemas ([#1092](https://github.com/Unique-AG/connectors/issues/1092)) ([142b461](https://github.com/Unique-AG/connectors/commit/142b46181fcfbb155958e7a4f10ad939c8cccb23))
* **sharepoint-connector,office-365-mcp,outlook-semantic-mcp,teams-mcp:** stop managing shared Microsoft service principals as destroyable resources ([#1097](https://github.com/Unique-AG/connectors/issues/1097)) ([e8cdadd](https://github.com/Unique-AG/connectors/commit/e8cdaddc16dfd1352797c8b450e8cd244abb0445))

## [Unreleased]

### Features

* **office-365-mcp:** add Teams chat and channel send tools
* **office-365-mcp:** add Teams message reactions and search include_body
* **office-365-mcp:** register Teams send tools and add a teams-write preset

## [0.2.3](https://github.com/Unique-AG/connectors/compare/office-365-mcp@0.2.2...office-365-mcp@0.2.3) (2026-09-23)


### Features

* **office-365-mcp:** add OneNote read, write and delete tools ([#1072](https://github.com/Unique-AG/connectors/issues/1072)) ([de6cb8a](https://github.com/Unique-AG/connectors/commit/de6cb8a92fd5a18792c65a6e4386a0394eedc7a9))
* **office-365-mcp:** read a transcript page without holding the transcript ([#1076](https://github.com/Unique-AG/connectors/issues/1076)) ([2c4740c](https://github.com/Unique-AG/connectors/commit/2c4740c9e17c4aedcfa4c6c532e073f2062bd214))


### Bug Fixes

* **office-365-mcp:** allow egress to sharepoint.com and svc.ms ([#1073](https://github.com/Unique-AG/connectors/issues/1073)) ([b3fd819](https://github.com/Unique-AG/connectors/commit/b3fd81969f2f4ce1d68cf196f5802fe5dc4b7269))


### Dependencies

* bump fastmcp[azure] in /services/office-365-mcp ([#1070](https://github.com/Unique-AG/connectors/issues/1070)) ([9a155b2](https://github.com/Unique-AG/connectors/commit/9a155b29b061f1695c26333b5ddb231cd64f932a))
* bump unique-toolkit[monitoring,otel] in /services/office-365-mcp ([#1069](https://github.com/Unique-AG/connectors/issues/1069)) ([9ee5127](https://github.com/Unique-AG/connectors/commit/9ee512721a837fa049495c2c538ad8848be3fd26))
* bump uvicorn[standard] in /services/* ([#1067](https://github.com/Unique-AG/connectors/issues/1067)) ([3b93279](https://github.com/Unique-AG/connectors/commit/3b93279c15e729feb9c62ce807134fd762f86432))

## [0.2.2](https://github.com/Unique-AG/connectors/compare/office-365-mcp@0.2.1...office-365-mcp@0.2.2) (2026-09-18)


### Features

* **office-365-mcp:** add SharePoint and OneDrive file tools ([#1048](https://github.com/Unique-AG/connectors/issues/1048)) ([cd8fef2](https://github.com/Unique-AG/connectors/commit/cd8fef23e179de7541fc133c3d26eb5a03b9e004))


### Dependencies

* pin lxml to 6.1.3, bump kiota ([#1050](https://github.com/Unique-AG/connectors/issues/1050)) ([122c820](https://github.com/Unique-AG/connectors/commit/122c820f8a4a0e150318d4c58c587bd4cd0b8919))

## [0.2.1](https://github.com/Unique-AG/connectors/compare/office-365-mcp@0.2.0...office-365-mcp@0.2.1) (2026-09-17)


### Features

* **office-365-mcp:** add server-side filters and date windows to the read tools ([#995](https://github.com/Unique-AG/connectors/issues/995)) ([ca52382](https://github.com/Unique-AG/connectors/commit/ca523825d013f64a5c90298ba6842911ed68aa26))


### Bug Fixes

* **backstop-mcp,hello-mcp,kb-mcp,office-365-mcp:** align the Python image build layouts ([#1038](https://github.com/Unique-AG/connectors/issues/1038)) ([ecdffb6](https://github.com/Unique-AG/connectors/commit/ecdffb656c2f9ed98217c2f4215b33bb9751efd9))


### Dependencies

* **backstop-mcp,hello-mcp,kb-mcp,office-365-mcp:** remove pip from the Python images ([#1033](https://github.com/Unique-AG/connectors/issues/1033)) ([3c0c51f](https://github.com/Unique-AG/connectors/commit/3c0c51f0feb886f41fcc7c6728cea9c040e30741))
* bump basedpyright in /packages/mcp-credential-auth ([#1026](https://github.com/Unique-AG/connectors/issues/1026)) ([61f0ddd](https://github.com/Unique-AG/connectors/commit/61f0dddee8a171e7d8f0398c5f23ada73f7a8b2f))
* bump mcp in /services/backstop-mcp ([#1024](https://github.com/Unique-AG/connectors/issues/1024)) ([f0f626f](https://github.com/Unique-AG/connectors/commit/f0f626fda57d873a783d7eac16e67e23f3393c02))
* bump ruff in /packages/mcp-credential-auth ([#1028](https://github.com/Unique-AG/connectors/issues/1028)) ([bb44f5a](https://github.com/Unique-AG/connectors/commit/bb44f5a5fce11f7022bb67d12f647a25336dddb4))
* bump unique-mcp in /services/office-365-mcp ([#1006](https://github.com/Unique-AG/connectors/issues/1006)) ([ff07e2e](https://github.com/Unique-AG/connectors/commit/ff07e2ed7e8a654c2802a5caabeca85517dda75d))
* **hello-mcp,kb-mcp,office-365-mcp:** apply Debian security updates in the Python runtime images ([#1022](https://github.com/Unique-AG/connectors/issues/1022)) ([83a61f8](https://github.com/Unique-AG/connectors/commit/83a61f88d73645a607300ac9dc7ae424a5b29294))

## [0.2.0](https://github.com/Unique-AG/connectors/compare/office-365-mcp@0.1.0...office-365-mcp@0.2.0) (2026-09-09)


### ⚠ BREAKING CHANGES

* **office-365-mcp:** add an Outlook mail surface of 14 tools, and prefix every Teams tool ([#868](https://github.com/Unique-AG/connectors/issues/868))

### Features

* **office-365-mcp:** accept ENTRA_TENANT_ID=organizations for multi-tenant registrations ([#909](https://github.com/Unique-AG/connectors/issues/909)) ([5858025](https://github.com/Unique-AG/connectors/commit/5858025ada29a13488ae6387223e8e13aa1fc8be))
* **office-365-mcp:** add an Outlook calendar surface of five tools ([#908](https://github.com/Unique-AG/connectors/issues/908)) ([6317ba7](https://github.com/Unique-AG/connectors/commit/6317ba7ba48960201a5300105a0c124036a75545))
* **office-365-mcp:** add an Outlook mail surface of 14 tools, and prefix every Teams tool ([#868](https://github.com/Unique-AG/connectors/issues/868)) ([4b9dfe9](https://github.com/Unique-AG/connectors/commit/4b9dfe93367bd31bde4e2e5be6b00a641fe20831))


### Bug Fixes

* **backstop-mcp,confluence-connector,hello-mcp,kb-mcp,office-365-mcp,outlook-semantic-mcp,sharepoint-connector,teams-mcp:** bump base chart dependency to 0.1.0-87990c ([#915](https://github.com/Unique-AG/connectors/issues/915)) ([1bc27a7](https://github.com/Unique-AG/connectors/commit/1bc27a713ab7e2a5bf36671fa1f1f294497c649e))
* **office-365-mcp:** confirm outlook_send_draft on both MCP protocol eras under fastmcp 4 ([#972](https://github.com/Unique-AG/connectors/issues/972)) ([6d8baa5](https://github.com/Unique-AG/connectors/commit/6d8baa5901e959c93f7ae8748ab8db388bbeb3af))
* **office-365-mcp:** raise the pod memory request and limit above the observed working set ([#869](https://github.com/Unique-AG/connectors/issues/869)) ([ff0812a](https://github.com/Unique-AG/connectors/commit/ff0812a66e15c2b97e76411226a906318a882773))


### Dependencies

* **backstop-mcp,hello-mcp,kb-mcp,office-365-mcp:** run the Python services on 3.14 ([#866](https://github.com/Unique-AG/connectors/issues/866)) ([7f2321a](https://github.com/Unique-AG/connectors/commit/7f2321afffb27bcd13e566eea12b0f4c6ceaecc1))
* **backstop-mcp,hello-mcp,kb-mcp,office-365-mcp:** update Python dependencies ([#864](https://github.com/Unique-AG/connectors/issues/864)) ([2833248](https://github.com/Unique-AG/connectors/commit/2833248838b4f6221ccf46f721146e5b1a17c0e4))
* bump msgraph-sdk in /services/office-365-mcp ([#956](https://github.com/Unique-AG/connectors/issues/956)) ([936dee6](https://github.com/Unique-AG/connectors/commit/936dee6749f73d7639c85bf383718e87acc8f1cb))
* bump pydantic in /services/kb-mcp ([#954](https://github.com/Unique-AG/connectors/issues/954)) ([f7ea6fd](https://github.com/Unique-AG/connectors/commit/f7ea6fde3fb8d5c7e33df42494f8c369a238336a))
* bump ruff from 0.16.4 to 0.16.5 in /services/office-365-mcp ([#933](https://github.com/Unique-AG/connectors/issues/933)) ([08be046](https://github.com/Unique-AG/connectors/commit/08be046bc6008e03d32f946b768374763a6c530c))
* bump ruff in /services/backstop-mcp ([#953](https://github.com/Unique-AG/connectors/issues/953)) ([3222aa2](https://github.com/Unique-AG/connectors/commit/3222aa2cf86c70f960674f48771f610d13eaf425))
* bump unique-toolkit[monitoring,otel] in /services/office-365-mcp ([#955](https://github.com/Unique-AG/connectors/issues/955)) ([707c7b5](https://github.com/Unique-AG/connectors/commit/707c7b517b70d86694e93ddd582238a1c10e1102))
* **office-365-mcp:** build and run on one interpreter ([#902](https://github.com/Unique-AG/connectors/issues/902)) ([b4088b1](https://github.com/Unique-AG/connectors/commit/b4088b11e43e4accb0cf40f4cb02e09d29e42f2d))
* **office-365-mcp:** move to fastmcp 4.0.2 ([#914](https://github.com/Unique-AG/connectors/issues/914)) ([c328bcc](https://github.com/Unique-AG/connectors/commit/c328bcce43e90b61cbf8bfb856057ed776933947))
* put every dependency in the right group, name what was missing, and hold shared versions in the pnpm catalog ([#958](https://github.com/Unique-AG/connectors/issues/958)) ([794092f](https://github.com/Unique-AG/connectors/commit/794092faa348052eddf2be580ed61fc771684b6f))
* upgrade uv to 0.12.10 in the Python images ([#975](https://github.com/Unique-AG/connectors/issues/975)) ([8fe0852](https://github.com/Unique-AG/connectors/commit/8fe08523405ddcacfd3fd616758bb8a306855079))

## 0.1.0 (2026-08-27)


### Features

* **office-365-mcp,ci:** add Entra application module with tool-composed Graph permissions ([#848](https://github.com/Unique-AG/connectors/issues/848)) ([f8241c7](https://github.com/Unique-AG/connectors/commit/f8241c7aeb456d9cec2e5c81b154ee9bc603097d))


### Bug Fixes

* **office-365-mcp:** align mcpConfig schema with sibling chart conventions ([#853](https://github.com/Unique-AG/connectors/issues/853)) ([16eb947](https://github.com/Unique-AG/connectors/commit/16eb947740ad72a68ea61d77714b80990fc7c785))


### Miscellaneous Chores

* **office-365-mcp:** name the service Office 365 in its description ([#839](https://github.com/Unique-AG/connectors/issues/839)) ([087c024](https://github.com/Unique-AG/connectors/commit/087c024800b7ab42cc3cc1be65227a9aa7b9ef60))
