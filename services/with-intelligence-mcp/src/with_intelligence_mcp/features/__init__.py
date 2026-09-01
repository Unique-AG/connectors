"""What the connector does, one package per slice of the domain.

A feature owns its own model layers (`api_responses` → `internal_dto` → `responses`), its
fetches, and the tools that expose them. It may read `config` freely — a feature is allowed to
be configured. What it may not do is import `server/`: the server wires features together, and
the reverse is an inversion. `tests/test_layering.py` enforces that.

Nothing lives here yet. The first slices are the vendor session (`auth/`), then the vocabulary
resolver every filter needs, then investors.
"""
