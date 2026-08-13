"""Feature implementations: what this connector actually does.

One module per slice of Microsoft 365 — `identity` (who the caller is), `chats` (their Teams
chats) and `message_search` (finding a Teams message) so far. Each owns three things that belong
together: the Graph request it makes, the shape it answers with, and the delegated Graph
permissions that request needs.

This side must not import from `server/`: the server wires features together, never the reverse.
`tests/test_layering.py` enforces it.
"""
