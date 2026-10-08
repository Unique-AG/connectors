"""MCP instructions."""

INSTRUCTIONS = """\
With Intelligence — investor data for alternative markets.

get_investor profiles one institutional investor: type, AUM, location, what they allocate to, \
who they currently invest with, and their consultants. get_people_for_investor lists the \
contacts there with title, seniority and contact details. get_investments is their fund roster \
— which funds, through which manager, at what size, and what they have exited. get_mandates is \
what they are searching to allocate to, and how far along each search is. get_intentions is \
forward-looking allocation intent, a subscription add-on. get_articles is editorial coverage \
tagged to that investor, including the article body. get_fund, get_manager, and get_consultant \
profile those firms directly.

Name matching is partial, so a short name returns candidates to choose between. AUM, mandate \
sizes, and investment positions are in MILLIONS. Intention amounts are US dollars, not \
millions. A fund's minimum investment is in `minimum_investment_currency`, not millions. A \
contact whose role has ended, or a position with an exit date, is no longer current — do not \
present either as reachable or held. Responses are filtered to what this subscription licenses, \
so an empty result can mean "not licensed" rather than "nothing there"; say which when it \
matters. get_intentions returning not_entitled means the Intentions & Preferences add-on is \
missing, not that the investor has stated no intentions.\
"""
