"""Feature implementations: what this connector actually does.

Everything here is domain logic — Backstop credential bridging (`auth`), CRM custom-field
schema discovery (`custom_fields`), name-to-record lookup (`party_resolver`), and the
resolution algebra the latter two share (`resolution`).

Layering rules, both enforced by `tests/test_layering.py`:

* **Nothing under `features/` may import from `server/`.** The server wires features together,
  never the reverse. That rule is what keeps a presentation concern from drifting back into a
  feature package, which is how `custom_fields` came to import `server.tools` before.
* **Nothing under `backstop_client/` may import from here.** Features may use the shared
  infrastructure (`backstop_client`, `db`, `config`, `logging`, `metrics`, `coerce`) freely, but
  that traffic is one-way: a type both sides need belongs in the infrastructure module, with
  `features/` supplying the implementation (see `backstop_client/credential.py`).
"""
