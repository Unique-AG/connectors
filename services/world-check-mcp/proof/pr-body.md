## Summary
- Scaffolds `world-check-mcp` from the LSEG World-Check One screening spec and registers it for release. Persistence stays empty: screening records remain in LSEG.
- Authenticates callers with Zitadel, and LSEG with a separate service-account client-credentials token. There is no token exchange. `MCP_AUTH_MODE=none` keeps the server on loopback.
- Adds handwritten read tools on top of the generated client: `list_groups`, `get_group_settings`, `get_case`, `get_case_reference`, `get_profile`, and `get_reference_data`. `get_api_info` is still served straight from the spec. Screening, monitoring, passport, and resolution are not in this pull request.

## Demo

Calls from the Inspector against the running server. The group name and LSEG ids are replaced.

```
$ inspector --method initialize
```

```json
{
  "serverInfo": {
    "name": "World Check MCP",
    "version": "0.0.0"
  },
  "protocolVersion": "2025-11-25",
  "capabilities": {
    "logging": {},
    "prompts": {
      "listChanged": true
    },
    "resources": {
      "subscribe": false,
      "listChanged": true
    },
    "tools": {
      "listChanged": true
    }
  },
  "instructions": "Screens people and organizations in LSEG World-Check One and returns sanctions, PEP, and adverse-media results for KYC and third-party due diligence."
}
```

```
$ inspector --method tools/list
```

```json
[
  "get_api_info",
  "get_case",
  "get_case_reference",
  "get_group_settings",
  "get_profile",
  "get_reference_data",
  "list_groups"
]
```

```
$ inspector --method tools/call --tool-name get_api_info
```

```json
{
  "version": "3.9.0",
  "systemDateTime": "2026-10-22T13:16:49.139Z"
}
```

```
$ inspector --method tools/call --tool-name list_groups
```

```json
[
  {
    "id": "example-id-00000000000001",
    "name": "Example group",
    "parent_id": null,
    "child_groups": []
  }
]
```

```
$ inspector --method tools/call --tool-name get_reference_data --tool-arg kind=api_info
```

```json
{
  "kind": "api_info",
  "names_by_code": null,
  "providers": null,
  "search_filters": null,
  "api_version": "3.9.0",
  "system_date_time": "2026-10-22T13:16:52.046Z"
}
```

```
$ inspector --method tools/call --tool-name get_group_settings --tool-arg group_id=example-id-00000000000001
```

```json
{
  "group": {
    "id": "example-id-00000000000001",
    "name": "Example group",
    "parent_id": null,
    "child_groups": []
  },
  "screening_type": "CASE_MANAGEMENT_AUDIT",
  "mandatory_provider_types": [
    "WATCHLIST"
  ],
  "secondary_fields": [
    {
      "type_id": "SFCT_1",
      "label": "GENDER",
      "entity_type": "individual",
      "required": false
    },
    {
      "type_id": "SFCT_2",
      "label": "DATE_OF_BIRTH",
      "entity_type": "individual",
      "required": false
    },
    {
      "type_id": "SFCT_3",
      "label": "COUNTRY_LOCATION",
      "entity_type": "individual",
      "required": false
    },
    {
      "type_id": "SFCT_4",
      "label": "PLACE_OF_BIRTH",
      "entity_type": "individual",
      "required": false
    },
    {
      "type_id": "SFCT_5",
      "label": "NATIONALITY",
      "entity_type": "individual",
      "required": false
    },
    {
      "type_id": "SFCT_191",
      "label": "DOCUMENT_ID",
      "entity_type": "individual",
      "required": false
    },
    {
      "type_id": "SFCT_192",
      "label": "DOCUMENT_ID_COUNTRY",
      "entity_type": "individual",
      "required": false
    },
    {
      "type_id": "SFCT_193",
      "label": "DOCUMENT_ID_TYPE",
      "entity_type": "individual",
      "required": false
    },
    {
      "type_id": "SFCT_191",
      "label": "DOCUMENT_ID",
      "entity_type": "unspecified",
      "required": false
    },
    {
      "type_id": "SFCT_192",
      "label": "DOCUMENT_ID_COUNTRY",
      "entity_type": "unspecified",
      "required": false
    },
    {
      "type_id": "SFCT_193",
      "label": "DOCUMENT_ID_TYPE",
      "entity_type": "unspecified",
      "required": false
    },
    {
      "type_id": "SFCT_7",
      "label": "IMO_NUMBER",
      "entity_type": "vessel",
      "required": false
    },
    {
      "type_id": "SFCT_6",
      "label": "REGISTERED_COUNTRY",
      "entity_type": "organisation",
      "required": false
    },
    {
      "type_id": "SFCT_191",
      "label": "DOCUMENT_ID",
      "entity_type": "organisation",
      "required": false
    },
    {
      "type_id": "SFCT_192",
      "label": "DOCUMENT_ID_COUNTRY",
      "entity_type": "organisation",
      "required": false
    },
    {
      "type_id": "SFCT_193",
      "label": "DOCUMENT_ID_TYPE",
      "entity_type": "organisation",
      "required": false
    },
    {
      "type_id": "SFCT_8",
      "label": "PASSPORT_GIVEN_NAMES",
      "entity_type": "individual",
      "required": true
    },
    {
      "type_id": "SFCT_9",
      "label": "PASSPORT_LAST_NAME",
      "entity_type": "individual",
      "required": true
    },
    {
      "type_id": "SFCT_10",
      "label": "PASSPORT_GENDER",
      "entity_type": "individual",
      "required": true
    },
    {
      "type_id": "SFCT_11",
      "label": "PASSPORT_ISSUING_STATE",
      "entity_type": "individual",
      "required": true
    },
    {
      "type_id": "SFCT_12",
      "label": "PASSPORT_NATIONALITY",
      "entity_type": "individual",
      "required": true
    },
    {
      "type_id": "SFCT_13",
      "label": "PASSPORT_DATE_OF_BIRTH",
      "entity_type": "individual",
      "required": true
    },
    {
      "type_id": "SFCT_14",
      "label": "PASSPORT_DOCUMENT_TYPE",
      "entity_type": "individual",
      "required": true
    },
    {
      "type_id": "SFCT_15",
      "label": "PASSPORT_ID_NUMBER",
      "entity_type": "individual",
      "required": true
    },
    {
      "type_id": "SFCT_16",
      "label": "PASSPORT_DATE_OF_EXPIRY",
      "entity_type": "individual",
      "required": true
    }
  ],
  "toolkits": [
    {
      "provider_type": "WATCHLIST",
      "statuses": [
        "POSITIVE",
        "POSSIBLE",
        "FALSE",
        "UNSPECIFIED"
      ],
      "risks": [
        "HIGH",
        "MEDIUM",
        "LOW",
        "UNKNOWN"
      ],
      "reasons": [
        "No Match",
        "Full Match",
        "Partial Match",
        "Unknown",
        "Auto-Resolved"
      ]
    }
  ]
}
```

```
$ inspector --method tools/call --tool-name get_case --tool-arg case=missing-case
```

```json
{
  "result": "No case matches missing-case.",
  "isError": true
}
```

## Test plan
- [ ] `uv run ruff check .` in `services/world-check-mcp`
- [ ] `uv run basedpyright`
- [ ] `uv run pytest -q`
- [ ] `uv run lint-imports`
- [ ] `uv run mcp-architecture-check`
- [ ] Confirm the diff against `show/world-check-python-cli` is the service plus its release registration

Made with [Cursor](https://cursor.com)
