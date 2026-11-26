"""The notes that keep a tool's titled and linked records out of the sources an answer cites.

Unique's chat cites every record of a tool result that carries a title and a link. A lookup or a
write returns such records too, yet the user checks a claim against what the agent read, not
against the folder it browsed or the draft it saved.
"""


def lookup_not_a_source(found: str, *, cite: str) -> str:
    return (
        f"Do not cite this tool's results: they help you find {found}, they are not sources. "
        + f"Cite {cite} instead."
    )


ACTION_NOT_A_SOURCE: str = (
    "Do not cite this tool's result: it reports a change, it is not a source."
)
