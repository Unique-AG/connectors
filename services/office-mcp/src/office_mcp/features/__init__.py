"""Feature implementations: what this connector actually does.

One module per slice of Microsoft 365 — `identity` (who the caller is), `chats` (their Teams
chats), `channels` (their teams, a team's channels and one channel's posts), `message_search`
(finding a Teams message) and `message_read` (reading one) so far. Each owns three things that
belong together: the Graph request it makes, the shape it answers with, and the delegated Graph
permissions that request needs.

A module may import another: `message_read` takes the handle grammar from `message_search`, where
handles are minted, and `channels` takes both the message shape and the "did a person write this"
test from `message_read`, so that a message means the same thing whichever tool produced it.

This side must not import from `server/`: the server wires features together, never the reverse.
`tests/test_layering.py` enforces it.
"""
