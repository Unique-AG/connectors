"""Short orientation FastMCP puts in context for every conversation.

Kept brief on purpose: this is present on every call. Field-level documentation lives on each
tool's output schema; include names live on the `include` parameter of `get_person` /
`get_organization`.
"""

INSTRUCTIONS = """\
Backstop CRM. People and organizations are the records; tools own different questions.

Contact details (emails, locations, primary contact, the organization a person works at): \
get_person / get_organization with `include`. `representative` is our internal account owner, \
not a way to reach the investor. Retired email addresses are flagged — do not write to them.

Meetings, calls, notes, emails, documents: get_activity_history, then get_activity_detail \
for a full body. Do not look for those on get_person / get_organization.

Pipeline stage and timing: get_opportunities. `previous_stage` is the stage the deal just \
left, not where it is now. There is no cursor; the whole party's pipeline is returned. \
Stage names are this instance's vocabulary, returned on each deal.

Custom-field names and types: list_custom_fields.
"""
