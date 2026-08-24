"""What must not disagree, and nothing else.

Every tool in `tools/` is a file of its own, and the one cost of that is that two files are free to
disagree. A thing belongs here when two tools would otherwise each need their own copy of it *and* a
difference between the copies would be a bug a caller could see. Anything one tool could own — a
description, an argument, an answer shape only it returns, a Graph request only it makes, a refusal
only it can explain — stays in that tool, or this package becomes the tool-declaration module the
tool files exist instead of.

No `__all__`: the *modules* are the units, and every consumer names the one it depends on at the
import line, which is the one thing this package exists to show.

Layering: nothing here imports `tools/`, and `seam.py` alone imports FastMCP. See
`tests/test_layering.py`, whose first rule is exactly that.
"""
