"""Feature implementations: what this connector actually does.

So far: Backstop credential bridging (`auth`), name-to-record lookup (`party_resolver`), the
shared entity-type vocabulary (`entity_types`), and the resolution algebra party/custom-field
resolution share (`resolution`). CRM custom-field schema discovery (`custom_fields`) and
read-response provenance / departed-contact detection (`data_hygiene`) land in later PRs, stacked
on top of this.

Layering rules, both enforced by `tests/test_layering.py`:

* **Nothing under `features/` may import from `server/`.** The server wires features together,
  never the reverse. That rule is what keeps a presentation concern from drifting back into a
  feature package.
* **Nothing under `backstop_client/` may import from here.** Features may use the shared
  infrastructure (`backstop_client`, `db`, `config`, `logging`, `metrics`, `coerce`) freely, but
  that traffic is one-way: a type both sides need belongs in the infrastructure module, with
  `features/` supplying the implementation (see `backstop_client/credential.py`).

Note the asymmetry in the first list item: `features/` may read `config` directly, while
`backstop_client/` may not (a third rule, also enforced by `tests/test_layering.py`). A feature is
allowed to be configured — `auth/cleanup.py` takes an `AuthConfig` and is clearer for it. A
transport is only allowed to be *told*: it takes the frozen settings types in
`backstop_client/settings.py`, which `create_app` translates config into.
"""
