"""Feature implementations: what this connector actually does.

Empty for now — the Microsoft Graph client, Entra auth, and the Microsoft 365 domain logic land
in later PRs, stacked on top of this scaffolding.

This side must not import from `server/`: the server wires features together, never the reverse.
`tests/test_layering.py` enforces it.
"""
