"""The one declaration of which tools this server exposes.

`create_app` registers from this list. A tool module that exists but is not listed here fails
`tests/test_layering.py` rather than shipping unreachable.
"""

from collections.abc import Awaitable, Callable

type ToolFunction = Callable[..., Awaitable[object]]

TOOLS: tuple[ToolFunction, ...] = ()
