"""What must not disagree, and nothing else.

Every tool in `tools/` is its own file. The one cost of that is that two files are free to
disagree.

A thing belongs here when two tools need their own copy of it, and a difference between the
copies is a bug that a caller can see. One tool can own a description, an argument, an answer
shape it alone returns, or a Graph request it alone makes. A refusal that only one tool can
explain also stays with that tool. Otherwise this package turns into one large tool-declaration
module, which is exactly what the separate tool files exist to prevent.

This package has no `__all__`. The modules are the units, and each consumer names the one it
depends on at the import line. That import line is the one thing this package exists to show.

A module that the tools of only one surface use goes in that surface's package: `outlook/`,
`teams/` or `sharepoint/`. A module that the tools of two or more surfaces use stays directly
here. A tool imports the modules of its own surface, the modules directly here, and the `seam`
package through its `__init__`, and never the modules of another surface. See rule 10 in
`tests/test_layering.py`.

Layering rule: nothing here imports `tools/`, and only the `seam/` package imports FastMCP. See
`tests/test_layering.py` for its first rule, which states exactly that.
"""
