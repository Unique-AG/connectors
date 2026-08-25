"""Feature implementations: what this connector actually does.

Everything here is domain logic — Backstop credential bridging (`auth`), CRM custom-field
catalog fetch (`custom_fields`), name-to-record lookup (`party_resolver`), product index and
match (`accounts`), people linked to an organization (`org_people`), read-response provenance
and departed-contact detection (`data_hygiene`), a person's or organization's interaction
record (`activity_history`), a party's pipeline (`opportunities`), the `?include=` allowlist
and the shapes side-loads project onto (`includes`), the shared entity-type vocabulary
(`entity_types`), and the resolution algebra party lookup uses (`resolution`).

MCP tools live under each feature's `tools/`: one `@tool` per file, named after the file.
They declare collaborators as `Depends(...)` parameters, which stay out of the published
schema. Long-lived collaborators are `@lru_cache(maxsize=1)` providers — cross-cutting ones
in `backstop_mcp.dependencies` (features may import this; it is not under `server/`),
feature-owned ones in `features/<f>/dependencies.py`, exported through the feature `__init__`.

Layering rules, both enforced by `tests/test_layering.py`:

* **Nothing under `features/` may import from `server/`.** The server wires features together,
  never the reverse. That rule is what keeps a presentation concern from drifting back into a
  feature package, which is how `custom_fields` came to import `server.tools` before. Tools
  do not import `server/` either; they take `Depends(...)`.
* **Nothing under `backstop_client/` may import from here.** Features may use the shared
  infrastructure (`backstop_client`, `db`, `config`, `logging`, `metrics`, `coerce`) freely, but
  that traffic is one-way: a type both sides need belongs in the infrastructure module, with
  `features/` supplying the implementation (see `backstop_client/credential.py`).

Note the asymmetry in the first list item: `features/` may read `config` directly, while
`backstop_client/` may not (a third rule, also enforced by `tests/test_layering.py`). A feature is
allowed to be configured — `auth/cleanup.py` takes an `AuthConfig` and is clearer for it. A
transport is only allowed to be *told*: it takes the frozen settings types in
`backstop_client/settings.py`, which `dependencies.transport_settings` translates config into.

Type names say which side of the boundary a shape sits on, which matters most where our shape has
stopped matching Backstop's:

* **`Backstop*`** — the transport that speaks HTTP/JSON:API to Backstop (`BackstopClient`,
  `BackstopApiResource`, `BackstopApiError`). The prefix means "this talks to Backstop", not
  "this data came from Backstop".
* **`*Attributes`** — a raw Backstop wire shape, 1:1 with their data model, under their field
  names (`CustomFieldDefinitionAttributes`).
* **`*Dto`** — computed internally and never published (`AccountRecordDto`, `ActivityItemDto`).
  A model that later ships to MCP clients moves to `*Response`.
* **`*Response`** — our curated, model-facing shape: trimmed, renamed where Backstop's naming
  would mislead, and documented for the model that consumes it. Used for nested pieces as much as
  for whole tool returns (`PersonRecordResponse`, `OrganizationRecordResponse`, `AttendeeResponse`,
  `EmploymentLinkResponse`).

Backstop's `emails` relationship is email *messages*, so the address book is exposed as
`email_addresses` holding a `ContactEmailResponse`. A `Backstop`-prefixed or `*Attributes` name
there would assert their shape at exactly the point our code stops matching it.
"""
