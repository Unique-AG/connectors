"""What the connector does, one package per slice of the domain.

A feature may read `config` freely but must not import `server/` — the server wires features
together, never the reverse (`tests/test_layering.py`). Nothing lives here yet.
"""
