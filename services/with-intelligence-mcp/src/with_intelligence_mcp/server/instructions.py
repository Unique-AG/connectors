"""Orientation FastMCP puts in context for every conversation. Kept brief: it is always present."""

INSTRUCTIONS = """\
With Intelligence — investor data for alternative markets: institutional investors and their \
contacts, fund rosters, mandates, allocation intentions, funds and managers, and editorial \
coverage.

get_investor profiles one institutional investor by name: type, AUM, location, the strategies \
and structures they allocate to, who they currently invest with, their consultants and key \
contacts. Several name matches come back as candidates to choose between.

Two things no field can tell you. An absent value is unknown to With Intelligence, never zero. \
And responses are filtered to what this subscription licenses — so an empty result, or \
`preferences_available: false`, can mean "not licensed" rather than "nothing there"; say which \
when it matters rather than reporting an absence as a fact about the investor.\
"""
