"""Short orientation FastMCP puts in context for every conversation.

Kept brief on purpose: this is present on every call. Field-level documentation lives on each
tool's output schema; include names live on the `include` parameter of `get_person` /
`get_organization`.
"""

INSTRUCTIONS = """\
Backstop CRM. People and organizations are the records; tools own different questions.

Contact details (emails, locations, primary contact, the organization a person works at): \
get_person / get_organization with `include`. `representative` is our internal account owner, \
not a way to reach the investor. Retired email addresses are flagged — do not write to them. \
People at an organization, with employment status there: get_people_for_party. \
`numberOfEmployees` on the organization record is not a roster.

Meetings, calls, notes, emails, documents: search_activities first. That primary is an \
undocumented UI search and may 404 — that is not "no activity exists". Fall back to \
get_activity_history (party-scoped only), then get_activity_detail for the full \
untruncated body. Prefer search_activities with include_description for note text \
while the primary answers. Do not look for those on get_person / get_organization.

Pipeline stage and timing: get_opportunities. `previous_stage` is the stage the deal just \
left, not where it is now. There is no cursor; the whole party's pipeline is returned. \
Stage names are this instance's vocabulary, returned on each deal.

Dated NAV, ITD performance, share of fund, lifetime in/out, and fund AUM: \
get_time_series on one account or one product, one series per call. A missing value \
on a dated point is "not in yet", not zero. `aums` is the product's total assets \
under management, not one investor's balance. Party holdings with snapshot balances: \
get_accounts_for_party. Prefer that for "how much does X have"; use get_time_series \
when the as-of date or ACTUAL/ESTIMATE status matters. Who is in a product, owners \
only, no figures: get_product_investors. Do not loop get_time_series over every \
account in a fund — fund-level AUM is get_time_series on the product's `aums`.

Custom-field names and types: list_custom_fields.
"""
