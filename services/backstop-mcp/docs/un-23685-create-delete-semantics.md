# UN-23685 create and delete semantics

Follow-up to `un-23685-write-semantics.md`. That file is the measured probe record; this one
is what the seven create/delete tools do with those measurements. No new live probing.

The tools live in the existing write packages (`org_people_writes`, `opportunity_writes`).
They are registered on `TOOLS` in `server/tools/registry.py`. Their `@lru_cache` factories
are on `PROVIDERS` in `teardown.py`.

| Tool | Package | Wire call |
| --- | --- | --- |
| `create_person` | `org_people_writes` | `POST /people`, then re-read |
| `create_organization` | `org_people_writes` | `POST /organizations`, then re-read |
| `create_employment` | `org_people_writes` | `POST /entity-relationships`, then re-read |
| `create_opportunity` | `opportunity_writes` | `POST /opportunities`, then re-read |
| `delete_person` | `org_people_writes` | locations-before-party cascade, then `DELETE /people/{id}` |
| `delete_organization` | `org_people_writes` | same cascade, then `DELETE /organizations/{id}` |
| `delete_opportunity` | `opportunity_writes` | `DELETE /opportunities/{id}` |

Deliberately not built:

- **`delete_employment`.** `end_employment` is the only removal path. Deleting the link
  erases history Backstop records nowhere else.
- Standalone contact-location create/delete tools. Already covered by `update_person` /
  `update_organization`.

Annotations on all seven: `read_only_hint=False`, `destructive_hint=True`,
`open_world_hint=False`, `idempotent_hint=False`. A repeated create makes a second record; a
repeated delete is a 404.

---

## Creates

Creates use the same writable-field bases and Python-name → wire-key builders as the
matching `update_*` tools. The builder's `omit_empty` flag is `True` on create: an empty
tuple is not sent. On update it is `False`, because an empty tuple **clears** a to-many.

POST, then **re-read** and report from the re-read. Backstop rewrites some values it
stores (phones: `+1 555 0100` lands as `555-0100`). Echoing the request as the stored
value is wrong.

Unknown `owner_login` is a `ToolError` **before any write**, via `SystemUsersService`, the
same as `update_person`.

### `create_person` / `create_organization`

Measured minimal 201 bodies:

- Person: `lastName` + `gender`.
- Organization: `name`.

There is no identity input and no location block. Location writes stay on `update_person` /
`update_organization`. `category_ids` is the initial set — a new record has nothing to
append to. Custom fields go through `update_custom_field_values`.

### `create_opportunity`

Four required fields: `name`, `currency_code`, `is_erisa`, and an investor party
(exactly one of `party_id` or `search`; `search_type` defaults to `contacts`). The
investor is resolved through the party resolver and sent as `relationships.investor`
with pointer type `contacts` — never a raw id and never `people`.

`stage` is a **name**, resolved through `OpportunityStagesService.find_by_stage_name`. It
**is** accepted on create (the swagger create example wrongly omits it). The response
reports the stage Backstop actually stored.

### `create_employment`

`start_date` is required. The payload is a hybrid, not interchangeable with a pure
JSON:API relationship body or a bulk-only body:

- `sourceEntity` / `destinationEntity` are `{resourceId, resourceType}` **attributes**
  (the same `resource_pointer` encoding as bulk).
- The type is `relationships.entityRelationshipType`.

The type **id** is resolved from `GET /entity-relationship-types` via
`EntityRelationshipTypesService.get_employment_type()`. The service is constructed with
`get_employment_rules()`: config ids when set, otherwise
`employment_relationship_type_markers`, excluding former-employment markers. No match or
more than one match is a `ToolError` listing the available names. Never hardcode a tenant
id (`456439` is this sandbox's).

One POST materialises **two mirror rows** (person→org and org→person). The response field
`created_mirror_row` is always `true`. `end_employment` is the removal path: one
`endDate` PATCH closes both rows.

---

## Deletes

Every delete is a schema-less `DELETE` — no `schema=`, no JSON body — expecting `204` with
an empty body. Backstop hard-deletes; there is no recycle bin. Success responses carry
`permanent=True`.

All three delete tools reuse `elicit_entity_deletion`. The prompt is built from a prior
read (callback, so the GET runs only when the client can elicit) and names what will be
destroyed. `DECLINED` → `ToolError` ("not confirmed / nothing was deleted").
`NOT_AVAILABLE` → proceed. That sits **alongside** `destructive_hint=True`, not instead of
it. UN-23685's "no second gate" decision was about updates.

### `delete_opportunity`

`DELETE /opportunities/{id}`. Input is `opportunity_id` only. The prompt names the deal
(`id` plus `name` when the GET has one).

### `delete_person` / `delete_organization`

Deleting a party does **not** cascade to its contact-locations. Survivors become
permanently undeletable: `GET /contact-locations/{id}` still `200`, but `DELETE` then
fails with `404 PartyNotFoundException` naming a party id the caller never mentioned.
Two such rows were stranded on the sandbox during the original probes.

`DeletePartyWithLocationsCommand` is the shared cascade both tools call:

1. `GET /{collection}/{id}?include=contactLocations` — **`contactLocations`**, never
   `include=locations` (hard `400`).
2. `DELETE /contact-locations/{location_id}` for each, through
   `ModifyContactLocationCommand` so `PartyNotFoundException` is translated.
3. Only then `DELETE /{collection}/{id}`.
4. If **any** location delete fails, abort **before** deleting the party and report which
   ones failed (and which were already removed). A partial failure is never a success
   response.

The success response reports `deleted_location_ids` (empty when there were none). The
elicitation prompt includes the location count — the part the user will not expect.

Identity is the same as `update_person` / `update_organization`: `search_type` plus
exactly one of `party_id` or `search`.

A null or empty location id must never reach the wire (`assert` upstream).
