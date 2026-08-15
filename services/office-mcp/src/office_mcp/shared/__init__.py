"""What must not disagree, and nothing else.

Every tool in `tools/` is a file of its own — its name, its description, its Graph permissions, its
arguments, its answer shape, its Graph request and its own error wording all in one place, so that
adding the eighth tool is adding one file and reading the seventh is reading one file. That is the
whole point, and it has exactly one cost: two files are free to disagree. This package is the list
of things they must not.

A thing belongs here when two tools would otherwise each need their own copy of it *and* a
difference between the copies would be a bug a caller could see:

* `handles.py` — the `teams:///` grammar. A handle minted by one tool and read by another is only
  readable while there is one definition of it; two spellers would not look like a disagreement,
  they would look like a handle one tool produced and another answers 404 to. The reply shape is
  the clearest case: only `browse_channel` can mint one and only `read_message` resolves it, and
  neither of them spells it.
* `messages.py` — what a Teams message is. A message browsed in a channel and the same message read
  by handle are the same type, normalised by the same function, or the two tools answer differently
  about the same message. The sender is where Graph's projections visibly differ — a search hit
  carries a mailbox-shaped `emailAddress` and every Teams read a `teamworkUserIdentity` with no
  email at all — and the Teams HTML a body arrives as is what nothing above here should ever see.
  It also holds `MAX_REPLIES_PER_POST`, the window on a channel thread: `browse_channel` applies
  it, and `search_messages` and `read_message` both have to describe it to explain why a reply a
  search found may have no handle that reads.
* `identity.py` — who the signed-in user is. `get_me` reports it; it is also the fact every other
  answer on this connector is correlated against, so a second tool asking it with a `GET /me` of
  its own would be a second answer to one question.
* `seam.py` — how a tool is attached to the outside: the On-Behalf-Of token it calls under and the
  advice a Graph refusal becomes. A model reads every refusal on this server as one voice, so the
  wording cannot be per tool.

What does *not* belong here is anything one tool could own: a description, an argument, an answer
shape only that tool returns, a Graph request only that tool makes, or a refusal only that tool can
explain. Moving one of those in is how this package becomes the tool-declaration module the tool
files exist instead of.

This is vocabulary rather than a layer, which is why it publishes no `__all__`: its *modules* are
the units, and every consumer names the one it depends on at the import line. An `__init__`
re-exporting the lot would hide the one thing the package exists to show — that two tools depend
on the same thing.

Layering: nothing here imports `tools/`, and `seam.py` alone imports FastMCP — see
`tests/test_layering.py`, whose first rule is exactly that.
"""
