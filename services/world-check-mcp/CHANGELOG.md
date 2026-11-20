# Changelog

## [0.1.1](https://github.com/Unique-AG/connectors/compare/world-check-mcp@0.1.0...world-check-mcp@0.1.1) (2026-11-20)


### Dependencies

* **deps:** bump authlib from 1.9.6 to 1.9.8 ([#1794](https://github.com/Unique-AG/connectors/issues/1794)) ([a737049](https://github.com/Unique-AG/connectors/commit/a737049e13c4ee3c25efbb95b9df7dcfd2284bd0))
* **deps:** bump cyclopts from 5.5.0 to 5.5.2 ([#1780](https://github.com/Unique-AG/connectors/issues/1780)) ([cac9f6f](https://github.com/Unique-AG/connectors/commit/cac9f6f1c2e94970c861c1fd128e8f0754769cb4))
* **deps:** bump httpx2 from 2.16.0 to 2.16.2 ([#1785](https://github.com/Unique-AG/connectors/issues/1785)) ([9613d9a](https://github.com/Unique-AG/connectors/commit/9613d9a5b39d60fcd92c0b6ad1f87a53e489c136))
* **deps:** bump numpy from 2.5.4 to 2.5.5 ([#1763](https://github.com/Unique-AG/connectors/issues/1763)) ([d5410b6](https://github.com/Unique-AG/connectors/commit/d5410b620f844177b4c6e6abb935da3350c3c4aa))
* **deps:** bump python-multipart from 0.0.33 to 0.0.34 ([#1795](https://github.com/Unique-AG/connectors/issues/1795)) ([e9308f1](https://github.com/Unique-AG/connectors/commit/e9308f15747922a00562d05a9bae9b0c084af7cc))
* **deps:** bump regex from 2026.11.9 to 2026.11.15 ([#1764](https://github.com/Unique-AG/connectors/issues/1764)) ([89a3c6a](https://github.com/Unique-AG/connectors/commit/89a3c6a7bdd760577bfb4cd981a7aec075d23d4c))

## 0.1.0 (2026-11-19)


### Features

* **services:** request offline_access from Zitadel for refresh tokens ([#1752](https://github.com/Unique-AG/connectors/issues/1752)) ([1894889](https://github.com/Unique-AG/connectors/commit/189488935ac0ff3a3184067b57f3a3660ceb2823))
* **world-check-mcp,ci,mcp-openapi,mcp-configs:** add the World-Check One MCP ([#1257](https://github.com/Unique-AG/connectors/issues/1257)) ([3ab2f3c](https://github.com/Unique-AG/connectors/commit/3ab2f3c945291f2674792a6fc303804ae768cf9d))
* **world-check-mcp:** add a Terraform module for the LSEG credential secrets ([#1578](https://github.com/Unique-AG/connectors/issues/1578)) ([f07e25a](https://github.com/Unique-AG/connectors/commit/f07e25a209f4baac44d3f22ceb878ffdf117b918))
* **world-check-mcp:** store sign-in and approval state in Postgres instead of Redis ([#1526](https://github.com/Unique-AG/connectors/issues/1526)) ([07199c2](https://github.com/Unique-AG/connectors/commit/07199c2398647ec65105206ad7504f2687229c59))


### Bug Fixes

* **world-check-mcp:** fall back to the resolved caseSystemId in get_case (UN-28955) ([#1610](https://github.com/Unique-AG/connectors/issues/1610)) ([5d6a0b0](https://github.com/Unique-AG/connectors/commit/5d6a0b0439bafd25e145fef98534603a27eeb301))
* **world-check-mcp:** fix the findings of an MCP review before the first release ([#1737](https://github.com/Unique-AG/connectors/issues/1737)) ([8ba4693](https://github.com/Unique-AG/connectors/commit/8ba4693fb872823fda521ab23e52c5183d977c55))
* **world-check-mcp:** raise UpstreamError for a malformed LSEG token response (UN-28956) ([#1608](https://github.com/Unique-AG/connectors/issues/1608)) ([03d1724](https://github.com/Unique-AG/connectors/commit/03d1724446f2b923961794381725de53d29bf4af))
* **world-check-mcp:** refuse an overlapping approved write on one case (UN-28951) ([#1617](https://github.com/Unique-AG/connectors/issues/1617)) ([142aaf3](https://github.com/Unique-AG/connectors/commit/142aaf3e419155346458871b53549339d81da835))
* **world-check-mcp:** reject future date of birth and malformed case_id in passport_check (UN-28963) ([#1607](https://github.com/Unique-AG/connectors/issues/1607)) ([1280220](https://github.com/Unique-AG/connectors/commit/12802209d7fd5bf74a6877e01d4be7e12628e7f3))
* **world-check-mcp:** report ongoing screening enabled when LSEG lists no failure (UN-28954) ([#1609](https://github.com/Unique-AG/connectors/issues/1609)) ([c3ce856](https://github.com/Unique-AG/connectors/commit/c3ce85684472c2a33ec74274a68c60b488c3498e))
* **world-check-mcp:** seal request_state with a key shared by every replica (UN-28949) ([#1613](https://github.com/Unique-AG/connectors/issues/1613)) ([2513c1d](https://github.com/Unique-AG/connectors/commit/2513c1d680bcd6ce6d944dd3697f47c15f525b74))
* **world-check-mcp:** serve stateful sessions so approvals work (UN-28950) ([#1619](https://github.com/Unique-AG/connectors/issues/1619)) ([8a04f32](https://github.com/Unique-AG/connectors/commit/8a04f320a010157a507bb7b374258fa1bef36055))
* **world-check-mcp:** skip OGS update rows without caseSystemId (UN-28958) ([#1611](https://github.com/Unique-AG/connectors/issues/1611)) ([8e8d2a8](https://github.com/Unique-AG/connectors/commit/8e8d2a83b8665d086752b5ed4d0ccfe5ca54bab5))


### Dependencies

* **deps:** bump anyio from 4.15.1 to 4.16.0 ([#1505](https://github.com/Unique-AG/connectors/issues/1505)) ([cd5f757](https://github.com/Unique-AG/connectors/commit/cd5f757849718d28a60a918814b8f67c28e961cc))
* **deps:** bump asgiref from 3.12.1 to 3.13.0 ([#1506](https://github.com/Unique-AG/connectors/issues/1506)) ([fbdd22c](https://github.com/Unique-AG/connectors/commit/fbdd22c46778d2901f70708e891e567af0759f9b))
* **deps:** bump authlib from 1.9.1 to 1.9.5 ([#1564](https://github.com/Unique-AG/connectors/issues/1564)) ([970fd93](https://github.com/Unique-AG/connectors/commit/970fd930ee2a9e14a0039158602384dd54772466))
* **deps:** bump authlib from 1.9.5 to 1.9.6 ([#1748](https://github.com/Unique-AG/connectors/issues/1748)) ([8c32dc1](https://github.com/Unique-AG/connectors/commit/8c32dc11ed0da23f0249d5698d8f3ff3e9da2afa))
* **deps:** bump azurerm from 5.12.0 to 5.13.0 ([#1572](https://github.com/Unique-AG/connectors/issues/1572)) ([697230b](https://github.com/Unique-AG/connectors/commit/697230b664bd3098f2a4902e2ae66c5cc028c478))
* **deps:** bump azurerm from 5.13.0 to 5.14.0 ([#1719](https://github.com/Unique-AG/connectors/issues/1719)) ([66e2f41](https://github.com/Unique-AG/connectors/commit/66e2f41280a3f3b1c491119fc3436689cc53abca))
* **deps:** bump caio from 0.12.9 to 0.12.10 ([#1508](https://github.com/Unique-AG/connectors/issues/1508)) ([ef5b307](https://github.com/Unique-AG/connectors/commit/ef5b30773b7688bb0da6312a2f8bd1af7067cf89))
* **deps:** bump certifi from 2026.10.19 to 2026.10.23 ([#1488](https://github.com/Unique-AG/connectors/issues/1488)) ([6e68315](https://github.com/Unique-AG/connectors/commit/6e6831529a6b2a01b2e8c2bfc328337a7f22b264))
* **deps:** bump click from 8.5.0 to 8.5.1 ([#1594](https://github.com/Unique-AG/connectors/issues/1594)) ([6b63621](https://github.com/Unique-AG/connectors/commit/6b636210023b5042d1431856495d42ea4e41bfac))
* **deps:** bump cyclopts from 5.2.0 to 5.3.3 ([#1509](https://github.com/Unique-AG/connectors/issues/1509)) ([2e82f58](https://github.com/Unique-AG/connectors/commit/2e82f58d7147237e1fe5d76884ca42b104097322))
* **deps:** bump cyclopts from 5.3.3 to 5.4.0 ([#1640](https://github.com/Unique-AG/connectors/issues/1640)) ([fb15e80](https://github.com/Unique-AG/connectors/commit/fb15e80557f0e19c6dfbcdaece0075f225f0b370))
* **deps:** bump cyclopts from 5.3.3 to 5.4.2 ([#1698](https://github.com/Unique-AG/connectors/issues/1698)) ([fc38cc2](https://github.com/Unique-AG/connectors/commit/fc38cc21ded9e058430d43ef2bd833dd4259be17))
* **deps:** bump cyclopts from 5.4.2 to 5.5.0 ([#1749](https://github.com/Unique-AG/connectors/issues/1749)) ([537e27b](https://github.com/Unique-AG/connectors/commit/537e27be4b64c3c51a281a9f8bbab455529dd1e0))
* **deps:** bump dnspython from 2.9.0 to 2.9.2 ([#1533](https://github.com/Unique-AG/connectors/issues/1533)) ([a7972c0](https://github.com/Unique-AG/connectors/commit/a7972c0eae54fc0dbcb801dc61b39b02c55e1998))
* **deps:** bump email-validator from 2.3.0 to 2.4.0 ([#1750](https://github.com/Unique-AG/connectors/issues/1750)) ([79df80f](https://github.com/Unique-AG/connectors/commit/79df80f6ed1ba3d9a7e52c7cae5efc0f7c0e32b6))
* **deps:** bump fastmcp packages ([#1530](https://github.com/Unique-AG/connectors/issues/1530)) ([eee2af2](https://github.com/Unique-AG/connectors/commit/eee2af2eb2ff4943ac89016ac463f86c192c5a67))
* **deps:** bump filelock from 4.2.4 to 4.2.9 ([#1547](https://github.com/Unique-AG/connectors/issues/1547)) ([e5e9b82](https://github.com/Unique-AG/connectors/commit/e5e9b82d43fa25487ff00cbbb609c8091ef107de))
* **deps:** bump filelock from 4.2.9 to 4.2.10 ([#1661](https://github.com/Unique-AG/connectors/issues/1661)) ([3a24a96](https://github.com/Unique-AG/connectors/commit/3a24a965bc6d139df14257504d03bcfd24233da4))
* **deps:** bump googleapis-common-protos from 1.75.5 to 1.76.0 ([#1512](https://github.com/Unique-AG/connectors/issues/1512)) ([6c1ad4d](https://github.com/Unique-AG/connectors/commit/6c1ad4da5a14018ff6c5b102185b3e445bb355dd))
* **deps:** bump griffelib from 2.4.0 to 2.4.1 ([#1513](https://github.com/Unique-AG/connectors/issues/1513)) ([39e3a63](https://github.com/Unique-AG/connectors/commit/39e3a6344f5bbaad9d97f4de81b70305132e2520))
* **deps:** bump grimp from 3.17 to 3.19 ([#1588](https://github.com/Unique-AG/connectors/issues/1588)) ([8e14f3a](https://github.com/Unique-AG/connectors/commit/8e14f3a4a6072c40162bbcb76132eecd7c983e05))
* **deps:** bump grimp from 3.19 to 3.20 ([#1728](https://github.com/Unique-AG/connectors/issues/1728)) ([eb121d2](https://github.com/Unique-AG/connectors/commit/eb121d291511143386941435c79ed3ed64610389))
* **deps:** bump hf-xet from 1.7.0 to 1.8.0 ([#1515](https://github.com/Unique-AG/connectors/issues/1515)) ([36def7c](https://github.com/Unique-AG/connectors/commit/36def7c41c67f3f20b79d2469f0fb8155cae8ba4))
* **deps:** bump import-linter from 2.15 to 2.16 ([#1595](https://github.com/Unique-AG/connectors/issues/1595)) ([999a723](https://github.com/Unique-AG/connectors/commit/999a723a80cc9486be995318e3ba3a32a6312c5a))
* **deps:** bump jiter from 0.17.0 to 0.19.0 ([#1589](https://github.com/Unique-AG/connectors/issues/1589)) ([7e02e08](https://github.com/Unique-AG/connectors/commit/7e02e08611f18bc9cb6cfd2d2bc34075041b10d1))
* **deps:** bump joserfc from 1.7.7 to 1.8.0 ([#1538](https://github.com/Unique-AG/connectors/issues/1538)) ([70bf11d](https://github.com/Unique-AG/connectors/commit/70bf11d7a2115d25496f8c56e8344296e1da7d02))
* **deps:** bump markdown-it-py from 4.2.0 to 4.3.0 ([#1668](https://github.com/Unique-AG/connectors/issues/1668)) ([de3ce06](https://github.com/Unique-AG/connectors/commit/de3ce068a0c8fb84db5f555da324b8ee2f8cc315))
* **deps:** bump multidict from 7.1.0 to 7.2.1 ([#1517](https://github.com/Unique-AG/connectors/issues/1517)) ([992c0b3](https://github.com/Unique-AG/connectors/commit/992c0b32acfc8bb481a2bca1f75ffc029e4a1cbd))
* **deps:** bump mypy-extensions from 1.1.0 to 1.2.0 ([#1539](https://github.com/Unique-AG/connectors/issues/1539)) ([b273eb8](https://github.com/Unique-AG/connectors/commit/b273eb82f74c5e38b3411ca9f4b7d0e22374eda1))
* **deps:** bump opentelemetry packages ([#1490](https://github.com/Unique-AG/connectors/issues/1490)) ([dc2cb18](https://github.com/Unique-AG/connectors/commit/dc2cb181b0be706ff0ad537f1da83430271cc6fd))
* **deps:** bump platformdirs from 4.13.5 to 4.14.5 ([#1548](https://github.com/Unique-AG/connectors/issues/1548)) ([1afb94c](https://github.com/Unique-AG/connectors/commit/1afb94c03fd6fb2c3a5b86a07a4ebdc7351ae096))
* **deps:** bump pycparser from 3.11 to 3.12 ([#1519](https://github.com/Unique-AG/connectors/issues/1519)) ([44aa69d](https://github.com/Unique-AG/connectors/commit/44aa69d12306b18060721dd581caae679012d151))
* **deps:** bump pydantic packages ([#1563](https://github.com/Unique-AG/connectors/issues/1563)) ([53901f0](https://github.com/Unique-AG/connectors/commit/53901f05119b7baf41e3936a84dfdeb4f4c04808))
* **deps:** bump pydantic-settings from 2.16.1 to 2.16.2 ([#1492](https://github.com/Unique-AG/connectors/issues/1492)) ([9732e7f](https://github.com/Unique-AG/connectors/commit/9732e7f5e0c50a454aa760412e69e852089bbda4))
* **deps:** bump pydantic-settings from 2.16.2 to 2.16.3 ([#1720](https://github.com/Unique-AG/connectors/issues/1720)) ([1d248c1](https://github.com/Unique-AG/connectors/commit/1d248c177601907f67d3bb0af5721cf4fe5e0da5))
* **deps:** bump pytest-asyncio from 1.4.1 to 1.4.1.post1 ([#1493](https://github.com/Unique-AG/connectors/issues/1493)) ([5e485ee](https://github.com/Unique-AG/connectors/commit/5e485ee64194e632f29887a66b8a54befc6df56d))
* **deps:** bump pytest-asyncio from 1.4.1.post1 to 1.5.0 ([#1701](https://github.com/Unique-AG/connectors/issues/1701)) ([aaf83d7](https://github.com/Unique-AG/connectors/commit/aaf83d711cb601fb1e93f9c6507bc2af2c4a13b0))
* **deps:** bump python-dateutil from 3.0.0 to 4.0.0 ([#1520](https://github.com/Unique-AG/connectors/issues/1520)) ([e243faa](https://github.com/Unique-AG/connectors/commit/e243faac0768c779af46e7f46f600627d53ebbb3))
* **deps:** bump python-multipart from 0.0.32 to 0.0.33 ([#1521](https://github.com/Unique-AG/connectors/issues/1521)) ([943daac](https://github.com/Unique-AG/connectors/commit/943daacfae613f953827de571661bf7295a0de04))
* **deps:** bump pytz from 2026.5 to 2026.6 ([#1522](https://github.com/Unique-AG/connectors/issues/1522)) ([92549c5](https://github.com/Unique-AG/connectors/commit/92549c56b55fde7104171c3b93801de109892623))
* **deps:** bump regex from 2026.11.7 to 2026.11.9 ([#1641](https://github.com/Unique-AG/connectors/issues/1641)) ([eb9ed19](https://github.com/Unique-AG/connectors/commit/eb9ed19fb498191a20c530d1beb178244565a85a))
* **deps:** bump regex from 2026.9.29 to 2026.11.7 ([#1596](https://github.com/Unique-AG/connectors/issues/1596)) ([2438875](https://github.com/Unique-AG/connectors/commit/2438875c516222430e8849996f4f17f5099a014c))
* **deps:** bump ruff from 0.17.3 to 0.17.4 ([#1573](https://github.com/Unique-AG/connectors/issues/1573)) ([7aad996](https://github.com/Unique-AG/connectors/commit/7aad99614439067376d84c4b79c0085a5a213b25))
* **deps:** bump ruff from 0.17.4 to 0.17.5 ([#1702](https://github.com/Unique-AG/connectors/issues/1702)) ([ead00ca](https://github.com/Unique-AG/connectors/commit/ead00cafd35fde6016e2d0f614575ae2e83ef1df))
* **deps:** bump sse-starlette from 3.5.0 to 3.7.0 ([#1601](https://github.com/Unique-AG/connectors/issues/1601)) ([0205d12](https://github.com/Unique-AG/connectors/commit/0205d12bd183e60b7655137546e9f7482c747226))
* **deps:** bump typing-inspection from 0.4.4 to 0.4.5 ([#1561](https://github.com/Unique-AG/connectors/issues/1561)) ([b5ba8b6](https://github.com/Unique-AG/connectors/commit/b5ba8b6a22630bdf68c55628c3ab5d3c8e258140))
* **deps:** bump tzdata from 2026.5 to 2026.6 ([#1494](https://github.com/Unique-AG/connectors/issues/1494)) ([459bd3b](https://github.com/Unique-AG/connectors/commit/459bd3b4adae20250df78c70eec33dda7df492db))
* **deps:** bump uncalled-for from 0.4.1 to 0.6.0 ([#1565](https://github.com/Unique-AG/connectors/issues/1565)) ([952417d](https://github.com/Unique-AG/connectors/commit/952417dd3595afbc4e4d73f893b7fa675775c936))
* **deps:** bump uncalled-for from 0.6.0 to 0.6.1 ([#1671](https://github.com/Unique-AG/connectors/issues/1671)) ([040c049](https://github.com/Unique-AG/connectors/commit/040c0493a01443a0ee87604114402bac7999719f))
* **deps:** bump unique packages ([#1585](https://github.com/Unique-AG/connectors/issues/1585)) ([bfeb189](https://github.com/Unique-AG/connectors/commit/bfeb189616648042eade65dcce8f4d6f5ae12c42))
* **deps:** bump unique packages ([#1692](https://github.com/Unique-AG/connectors/issues/1692)) ([44717f1](https://github.com/Unique-AG/connectors/commit/44717f16b84c1fd7c55dca389fb0c7e6069c71be))
* **deps:** bump websockets from 17.3 to 17.4 ([#1524](https://github.com/Unique-AG/connectors/issues/1524)) ([0ed6b78](https://github.com/Unique-AG/connectors/commit/0ed6b787007e2aa6a30ce592daa4af21954bb6fc))
* **deps:** bump wrapt from 2.5.1 to 2.5.2 ([#1525](https://github.com/Unique-AG/connectors/issues/1525)) ([a1f2779](https://github.com/Unique-AG/connectors/commit/a1f2779d6e097fb462f0d9c548b80ef3593441e7))
* **main:** align the python base image digest in every Dockerfile ([#1628](https://github.com/Unique-AG/connectors/issues/1628)) ([39e8acc](https://github.com/Unique-AG/connectors/commit/39e8accc2659fc07af97f2c23ea5910d984dcb7b))
* **world-check-mcp:** pin chart to base 0.1.0-3aa55e (UN-28952) ([#1612](https://github.com/Unique-AG/connectors/issues/1612)) ([3f3d9e7](https://github.com/Unique-AG/connectors/commit/3f3d9e7d1635b70cbff08640316c82a5cca9224f))
