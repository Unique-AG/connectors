"""Orientation FastMCP puts in context for every conversation. Kept brief: it is always present."""

INSTRUCTIONS = """\
With Intelligence — investor data for alternative markets.

get_investor profiles one institutional investor: type, AUM, location, what they allocate to, \
who they currently invest with, and their consultants. get_people_for_investor lists the \
contacts there with title, seniority and contact details. get_investments is their fund roster \
— which funds, through which manager, at what size, and what they have exited. get_mandates is \
what they are searching to allocate to, and how far along each search is.

Four things no field can tell you. Name matching is partial, so a short name returns candidates \
to choose between. Every money figure is in MILLIONS. A contact whose role has ended, or a \
position with an exit date, is no longer current — do not present either as reachable or held. \
And responses are filtered to what this subscription licenses, so an empty result can mean \
"not licensed" rather than "nothing there"; say which when it matters.\
"""
