"""Feature implementations: what this connector actually does.

One module per slice of Microsoft 365 — `identity` (who the caller is), `chats` (their Teams
chats), `channels` (their teams, a team's channels and one channel's posts), `message_search`
(finding a Teams message), `message_read` (reading one), `transcripts` (a meeting's transcripts, and
the words in one) and `recordings` (whether a meeting was recorded, and who may fetch the video) so
far. Each owns three things that belong together: the Graph request it makes, the shape it answers
with, and the delegated Graph permissions that request needs.

A module may import another: `message_read` takes the handle grammar from `message_search`, where
message handles are minted, `channels` takes both the message shape and the "did a person write
this" test from `message_read`, so that a message means the same thing whichever tool produced it,
and `chats` takes the meeting handle from `transcripts`, which owns that family for the same reason
— a chat is where a meeting's join URL comes from, and one grammar with two spellers is two
grammars. `recordings` borrows the most: the handle, the join-URL resolve, the occurrence window,
the newest-first walk over a meeting's artifacts and the "is an empty answer settled" inference all
come from `transcripts`, because both artifacts are asked for by the same handle over the same
window — and a promise about order or about absence that the two made separately is a promise they
would keep differently. What it does not borrow is why the two are
separate tools rather than one — Microsoft gates transcripts behind a tenant switch that is off by
default and gates recordings behind nothing of the kind, so a single tool would answer nothing
about a reachable recording in the commonest tenant. `recordings` argues that where the decision
was taken.

This side must not import from `server/`: the server wires features together, never the reverse.
`tests/test_layering.py` enforces it.
"""
