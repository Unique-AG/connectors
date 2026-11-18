import re
from collections.abc import Sequence

ONE_ADDRESS = re.compile(r"\A[^\s<>,;:\"@]+@[^\s<>,;:\"@]+\Z")


def repeated_address(addresses: Sequence[str]) -> str | None:
    named: set[str] = set()
    for address in addresses:
        if address.casefold() in named:
            return address
        named.add(address.casefold())
    return None
