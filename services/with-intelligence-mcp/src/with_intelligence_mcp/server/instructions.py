"""Short orientation FastMCP puts in context for every conversation.

Kept brief on purpose: this is present on every call, so field-level documentation belongs on
each tool's output schema instead. It gets written properly once there are tools to orient a
model between — the two things it will have to say, because no schema can, are that an empty
result may mean "your subscription does not cover this" rather than "there is nothing", and
that filters are vocabularies rather than free text.
"""

INSTRUCTIONS = """\
With Intelligence — investor data for alternative markets: institutional investors and their \
contacts, fund rosters, mandates, allocation intentions, funds and managers, and editorial \
coverage.

No tools are registered yet.\
"""
