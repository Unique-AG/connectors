from collections.abc import Mapping


def presence_flags(arguments: Mapping[str, object], *names: str) -> dict[str, bool]:
    """`has_<name>` per argument, so a search filter reaches telemetry without its value."""
    return {f"has_{name}": arguments[name] is not None for name in names}
