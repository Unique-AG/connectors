"""Feature implementations: what this connector actually does.

One module per slice of Microsoft 365 — `identity` (who the caller is) and `chats` (their Teams
chats) so far. Each owns three things that belong together: the Graph request it makes, the shape
it answers with, and the delegated Graph permission that request needs.

This side must not import from `server/`: the server wires features together, never the reverse.
`tests/test_layering.py` enforces it.
"""
