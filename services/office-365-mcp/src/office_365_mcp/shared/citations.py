"""Notes that keep titled, linked lookup and write results out of the cited sources."""


def lookup_not_a_source(found: str, *, cite: str) -> str:
    return (
        f"Do not cite this tool's results: they help you find {found}, they are not sources. "
        + f"Cite {cite} instead."
    )


ACTION_NOT_A_SOURCE: str = (
    "Do not cite this tool's result: it reports a change, it is not a source."
)
