"""Made-up Polixis responses, shaped like what the live API sent in November 2026.

Each pid is a real-format pid, its letter and 32 hex digits, written below as the letter and
its last three digits: O100 is O00000000000000000000000000000100.

The network around Example Holdings AG (O100), which `PATHS` and `SANCTION_EXPOSURE` follow too:

    Anna Example (P200) --shareholder 60%--> O100 --shareholder/ founder 100%--> O300
    Boris Sample (P400, SANCTION) --director, former--> Example Shipping Ltd (O300)
    Pia Example (P210) --director--> O100, and --director--> Example Consulting GmbH (O310, STATECO)
    Paul Sample (P230) --business partner--> P210, and --owner--> Example Bakery Sàrl (O320)
    O500 (STATECO) --power of attorney--> O100, in the full graph only, so it has no name
"""

UNKNOWN_PID = "P0000000000000000000000000000dead"
# Polixis answers a request about it with a 500, in the profile and in the full graph.
FAILING_PID = "P0000000000000000000000000000fa11"
# A group Polixis dissolved: `/api/graph/pid` answers it with a 410 that lists its former members.
DISSOLVED_PID = "U00000000000000000000000000000d15"

DISSOLVED: dict[str, object] = {
    "references": ["O00000000000000000000000000000100", "O00000000000000000000000000000101"]
}

REJECTION: dict[str, object] = {
    "error": f"Invalid Ardis ID: {UNKNOWN_PID}",
    "code": "VALIDATION",
    "timestamp": 1,
}

SEARCH: dict[str, object] = {
    "hits": [
        {
            "pid": "O00000000000000000000000000000100",
            "entityType": "ORGANIZATION",
            "names": [
                "Example Holdings SA",
                "Example Holdings AG",
                "Example Holdings SA",
                "Example Holdings Ltd",
            ],
            "sanction": True,
            "pep": False,
            "alerts": [
                {"description": "Listed company", "type": ["listed"]},
                {"description": "An internal marker", "type": ["hidden"]},
            ],
            "nameRecords": [
                {"original": "Example Holdings SA", "en": "Example Holdings SA", "type": "ALIAS"},
                {
                    "original": "Example Holdings AG",
                    "en": "Example Holdings AG",
                    "language": "de",
                    "type": "CURRENT_NAME",
                },
            ],
            "dates": {"Registration Date": [{"y": 1998, "m": 2}, {"y": 1998, "m": 2, "d": 3}]},
            "unis": {"Registration Number": ["CHE-000.000.001"]},
            "sanctionStatuses": {"Example Sanctions List": "ACTIVE"},
            "countries": ["ch", "li"],
            "addresses": ["1 Example Street", "2 Example Street", "3 Example Street", "4 Street"],
        },
        {"entityType": "PERSON", "names": ["A hit without a pid"]},
    ],
    "pagination": {"page": 1, "size": 10, "totalHits": 12, "hasNext": True},
}

PROFILE: dict[str, object] = {
    "names": {"original": ["Anna Beispiel"], "en": ["Anna Example"]},
    "nameRecords": [
        {
            "original": "Anna Beispiel",
            "en": "Anna Example",
            "language": "de",
            "type": "CURRENT_NAME",
        }
    ],
    "unis": {"National ID": ["756.0000.0000.01"]},
    "countries": {"countryCitizenship": ["ch"]},
    "dates": {"Date of Birth": [{"y": 1971, "m": 3}]},
    "gender": "f",
    "flags": ["PEP", "SANCTIONED", "#REP", "#PEP"],
    "alertList": [
        {"category": "PEP", "message": "Member of an example parliament"},
        {"category": "hidden", "message": "An internal marker"},
    ],
    "sanctionStatuses": {},
    "sanctions": {
        "Example Sanctions List": [
            {
                "country": "CH",
                "details": {"Sanction Status": ["DELISTED"], "Program": ["Example programme"]},
            }
        ]
    },
    "positions": [
        {
            "position": "Member of Parliament",
            "institution": "Example Parliament",
            "startDate": {"y": 2015},
            "endDate": {"y": 2023, "m": 12, "d": 31},
        }
    ],
}

_ANNA = {
    "id": "entity_ch_registry__p_1",
    "pid": "P00000000000000000000000000000200",
    "type": "PERSON",
    "names": [{"original": "Anna Beispiel", "en": "Anna Example", "language": "de"}],
    "countries": {"country": ["ch"], "countryCitizenship": ["ch", "li"]},
    "flags": [{"PEP": {"value": "#PEP"}}],
    "alerts": [
        {"description": "Politically exposed person", "type": ["pep"]},
        {"description": "An internal marker", "type": ["hidden"]},
    ],
    "uni": {"National ID": "756.0000.0000.01"},
}

# Live, the paged profile stays grouped by publisher, each group paged on its own, and a party
# two publishers report comes in both groups.
RELATED_PARTIES: dict[str, object] = {
    "root": {"pid": "O00000000000000000000000000000100", "type": "ORGANIZATION"},
    "related": {
        "Example Commercial Register": {
            "data": [
                {
                    "entity": {"type": "PERSON", "names": [{"en": "Pat Signatory"}]},
                    "relation": [
                        {
                            "type": "signature",
                            "relationProperty": [{"title": "signatory", "former": True}],
                        }
                    ],
                },
                {
                    "entity": _ANNA,
                    "relation": [
                        {
                            "type": "shareholding_ownership",
                            "relationProperty": [
                                {
                                    "title": "shareholder",
                                    "dates": {
                                        "Start Date": {"y": 2019, "m": 5},
                                        "Date of Information": {"y": 2026, "m": 10, "d": 1},
                                    },
                                    "properties": {
                                        "Share": ["60.00000"],
                                        "Share capital": ["100000"],
                                    },
                                    "metadata": {
                                        "sourceCode": "#CH_REGISTRY",
                                        "sourceName": "Example Commercial Register",
                                    },
                                }
                            ],
                        }
                    ],
                },
                {"entity": {"type": "ORGANIZATION", "names": []}, "relation": []},
            ],
            "currentPage": 0,
            "pageSize": 3,
            "totalElements": 3,
            "hasNext": False,
        },
        "Example PEP List": {
            "data": [
                {
                    "entity": {**_ANNA, "countries": {"country": ["de"]}},
                    "relation": [
                        {
                            "type": "board",
                            "relationProperty": [
                                {
                                    "title": "board member",
                                    "metadata": {"sourceName": "Example PEP List"},
                                }
                            ],
                        }
                    ],
                }
            ],
            "currentPage": 0,
            "pageSize": 1,
            "totalElements": 41,
            "hasNext": True,
        },
    },
}

OWNERS: dict[str, object] = {
    "startId": "O00000000000000000000000000000100",
    "totalNodes": 3,
    "truncated": False,
    "roots": [
        {
            "id": "O00000000000000000000000000000600",
            "type": "ORGANIZATION",
            "sharePercent": 80.0,
            "role": "shareholder",
            "children": [
                {
                    "id": "P00000000000000000000000000000700",
                    "type": "PERSON",
                    "sharePercent": 50.0,
                    "role": "shareholder",
                    "flags": ["PEP"],
                }
            ],
        },
        {
            "id": "P00000000000000000000000000000200",
            "type": "PERSON",
            "sharePercent": 20.0,
            "role": "shareholder",
        },
        {
            "id": "P00000000000000000000000000000200",
            "type": "PERSON",
            "sharePercent": 20.0,
            "role": "beneficial owner",
            "flags": ["SANCTION"],
        },
        {
            "id": "P00000000000000000000000000000700",
            "type": "PERSON",
            "sharePercent": 10.0,
            "role": "reported shareholder",
        },
    ],
    "meta": {
        "O00000000000000000000000000000600": {
            "names": {"original": ["Example Parent AG"], "en": ["Example Parent AG"]}
        },
        "P00000000000000000000000000000700": {
            "names": {"original": ["Carla Sample"], "en": ["Carla Sample"]}
        },
        "P00000000000000000000000000000200": {
            "names": {"original": ["Anna Beispiel"], "en": ["Anna Example"]}
        },
    },
}

HOLDINGS: dict[str, object] = {
    "startId": "O00000000000000000000000000000100",
    "totalNodes": 2,
    "truncated": True,
    "roots": [
        {
            "id": "O00000000000000000000000000000300",
            "type": "ORGANIZATION",
            "sharePercent": 100.0,
            "role": "shareholder/ founder",
            "alerts": ["STATECO", "HIDDEN"],
            "children": [
                {
                    "id": "O00000000000000000000000000000800",
                    "type": "ORGANIZATION",
                    "sharePercent": 0.0,
                    "role": "reported minority shareholder",
                }
            ],
        }
    ],
    "meta": {
        "O00000000000000000000000000000300": {"names": {"original": ["Example Shipping Ltd"]}}
    },
}

_KEY_NODES: dict[str, object] = {
    "O00000000000000000000000000000100": {
        "id": "O00000000000000000000000000000100",
        "type": "ORGANIZATION",
        "radii": [0],
    },
    "P00000000000000000000000000000200": {
        "id": "P00000000000000000000000000000200",
        "type": "PERSON",
        "radii": [1],
        "flags": ["PEP"],
    },
    "O00000000000000000000000000000300": {
        "id": "O00000000000000000000000000000300",
        "type": "ORGANIZATION",
        "radii": [1],
    },
    "P00000000000000000000000000000400": {
        "id": "P00000000000000000000000000000400",
        "type": "PERSON",
        "radii": [2],
        "flags": ["SANCTION"],
    },
    "P00000000000000000000000000000210": {
        "id": "P00000000000000000000000000000210",
        "type": "PERSON",
        "radii": [1],
    },
    "O00000000000000000000000000000310": {
        "id": "O00000000000000000000000000000310",
        "type": "ORGANIZATION",
        "radii": [2],
        "alertNames": ["STATECO", "HIDDEN"],
    },
    "P00000000000000000000000000000230": {
        "id": "P00000000000000000000000000000230",
        "type": "PERSON",
        "radii": [2],
    },
    "O00000000000000000000000000000320": {
        "id": "O00000000000000000000000000000320",
        "type": "ORGANIZATION",
        "radii": [3],
    },
}

_KEY_EDGES: list[object] = [
    {
        "sourceId": "O00000000000000000000000000000100",
        "targetId": "O00000000000000000000000000000300",
        "details": [
            {"role": "shareholder/ founder", "ctg": 11, "share": 100.0, "startDate": 1388448000}
        ],
    },
    {
        "sourceId": "P00000000000000000000000000000400",
        "targetId": "O00000000000000000000000000000300",
        "details": [{"role": "director", "ctg": 8, "former": True}],
    },
    {
        "sourceId": "P00000000000000000000000000000200",
        "targetId": "O00000000000000000000000000000100",
        "details": [{"role": "shareholder", "ctg": 11, "share": 60.0}],
    },
    {
        "sourceId": "P00000000000000000000000000000210",
        "targetId": "O00000000000000000000000000000100",
        "details": [{"role": "director", "ctg": 10}],
    },
    {
        "sourceId": "P00000000000000000000000000000210",
        "targetId": "O00000000000000000000000000000310",
        "details": [{"role": "director", "ctg": 10}],
    },
    {
        "sourceId": "P00000000000000000000000000000230",
        "targetId": "P00000000000000000000000000000210",
        "details": [{"role": "business partner", "ctg": 9}],
    },
    {
        "sourceId": "P00000000000000000000000000000230",
        "targetId": "O00000000000000000000000000000320",
        "details": [{"role": "owner", "ctg": 11}],
    },
]

KEY_GRAPH: dict[str, object] = {
    "root": _KEY_NODES["O00000000000000000000000000000100"],
    "nodes": _KEY_NODES,
    "edges": _KEY_EDGES,
    "meta": {
        "O00000000000000000000000000000100": {"names": {"en": ["Example Holdings AG"]}},
        "P00000000000000000000000000000200": {
            "names": {"original": ["Anna Beispiel"], "en": ["Anna Example"]}
        },
        "O00000000000000000000000000000300": {"names": {"original": ["Example Shipping Ltd"]}},
        "P00000000000000000000000000000400": {"names": {"en": ["Boris Sample"]}},
        "P00000000000000000000000000000210": {"names": {"en": ["Pia Example"]}},
        "O00000000000000000000000000000310": {"names": {"en": ["Example Consulting GmbH"]}},
        "P00000000000000000000000000000230": {"names": {"en": ["Paul Sample"]}},
        "O00000000000000000000000000000320": {"names": {"en": ["Example Bakery Sàrl"]}},
    },
}

FULL_GRAPH: dict[str, object] = {
    "root": _KEY_NODES["O00000000000000000000000000000100"],
    "nodes": {
        **_KEY_NODES,
        "O00000000000000000000000000000500": {
            "id": "O00000000000000000000000000000500",
            "type": "ORGANIZATION",
            "radii": [1],
            "alertNames": ["STATECO"],
        },
    },
    "truncated": True,
    "edges": [
        *_KEY_EDGES,
        {
            "sourceId": "O00000000000000000000000000000500",
            "targetId": "O00000000000000000000000000000100",
            "details": [{"role": "power of attorney", "ctg": 0}],
        },
    ],
    "empty": False,
}

SANCTION_EXPOSURE: dict[str, object] = {
    "directSanctions": [
        {
            "country": "CA",
            "details": {
                "Source": ["Example Autonomous Sanctions"],
                "Listing Date": ["2022-02-24"],
                "Sanction Status": ["ACTIVE"],
            },
        }
    ],
    "relatedSanctions": [
        {
            "pid": "P00000000000000000000000000000400",
            "nameEn": "Boris Sample",
            "countries": {"country": ["cy"]},
            "sanctions": {
                "Example Sanctions List": [
                    {
                        "country": "US",
                        "details": {
                            "Sanction Status": ["ACTIVE"],
                            "Program": ["EXAMPLE-EO1"],
                            "Listing Date": ["14-Apr-2022"],
                        },
                    }
                ]
            },
            "relationPaths": [
                {
                    "connection": {"role": "shareholder/ founder", "ctg": 11, "share": 100.0},
                    "sourceName": "Example Holdings AG",
                    "targetName": "Example Shipping Ltd",
                },
                {
                    "connection": {"role": "reported shareholder", "ctg": 11, "share": 100.0},
                    "sourceName": "Example Holdings AG",
                    "targetName": "Example Shipping Ltd",
                },
                {
                    "connection": {"role": "director", "ctg": 8, "former": True},
                    "sourceName": "Boris Sample",
                    "targetName": "Example Shipping Ltd",
                },
            ],
        },
        {
            "pid": "O00000000000000000000000000000900",
            "nameEn": "Example Trading FZE",
            "sanctions": {
                "Example Sanctions List": [
                    {
                        "details": {
                            "Sanction Status": ["DELISTED"],
                            "#UK_DESIGNATED_DATE": ["13/06/2024"],
                        }
                    }
                ]
            },
            "relationPaths": [
                {
                    "connection": {"role": "supplier", "ctg": 4, "startDate": 1388448000},
                    "sourceName": "Example Trading FZE",
                    "targetName": "Example Holdings AG",
                }
            ],
        },
        {"nameEn": "A party without a pid"},
    ],
}

_PATH_NODES: list[object] = [
    {
        "id": "P00000000000000000000000000000200",
        "type": "PERSON",
        "composite": True,
        "flags": ["PEP"],
    },
    {
        "id": "P00000000000000000000000000000200",
        "type": "PERSON",
        "composite": True,
        "flags": ["PEP"],
    },
    {"id": "O00000000000000000000000000000100", "type": "ORGANIZATION"},
    {
        "id": "O00000000000000000000000000000300",
        "type": "ORGANIZATION",
        "alertNames": ["STATECO", "HIDDEN"],
    },
    {"id": "P00000000000000000000000000000400", "type": "PERSON", "flags": ["SANCTION"]},
]

PATHS: dict[str, object] = {
    "paths": [
        {
            "nodes": _PATH_NODES,
            "edges": [
                {
                    "sourceId": "P00000000000000000000000000000400",
                    "targetId": "O00000000000000000000000000000300",
                    "details": [{"role": "director"}],
                },
                {
                    "sourceId": "P00000000000000000000000000000200",
                    "targetId": "O00000000000000000000000000000100",
                    "details": [{"role": "shareholder", "ctg": 11, "share": 60.0}],
                },
                {
                    "sourceId": "O00000000000000000000000000000100",
                    "targetId": "O00000000000000000000000000000300",
                    "details": [{"role": "shareholder/ founder", "share": 100.0}],
                },
            ],
        }
    ],
    "meta": KEY_GRAPH["meta"],
}

NO_PATHS: dict[str, object] = {"paths": [], "meta": {}}

JUDICIAL: dict[str, object] = {
    "rootJudicialDetails": {
        "ch": [
            {
                "id": "ch_2019_1",
                "courtType": "Federal Court",
                "country": "ch",
                "year": "2019",
                "snippet": ["the appeal of <em>Example Holdings AG</em> is dismissed"],
                "content": "A" * 40_000,
            }
        ]
    },
    "relatedJudicialDetails": {
        "DE": [
            {
                "id": "de_2023_7",
                "courtType": "Regional Court",
                "country": "DE",
                "year": "2023",
                "snippet": ["<em>Anna Example</em> as witness"],
                "content": "B" * 100,
            }
        ]
    },
}
