"""Feature implementations: what this connector actually does.

Everything here is domain logic — Backstop credential bridging (`auth`), CRM custom-field
schema discovery (`custom_fields`), name-to-record lookup (`party_resolver`), and the
resolution algebra the latter two share (`resolution`).

Layering rule, enforced by `tests/test_layering.py`: **nothing under `features/` may import
from `server/`.** Features may use the shared infrastructure (`backstop_client`, `db`,
`config`, `logging`, `metrics`, `coerce`); the server wires features together, never the
reverse. That rule is what keeps a presentation concern from drifting back into a feature
package, which is how `custom_fields` came to import `server.tools` before.
"""
