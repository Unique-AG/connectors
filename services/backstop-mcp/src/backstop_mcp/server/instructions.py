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
People at an organization, with employment status and categories there: get_people_for_party. \
`numberOfEmployees` on the organization record is not a roster. Custom-field values live on \
the party (get_organization / get_person), not on get_people_for_party.

Holdings: get_accounts_for_party first (undocumented table-data; may 404 — that is not \
"holds nothing"; the tool then falls back internally to the documented /accounts walk). \
Dated NAV, ITD, share of fund, lifetime in/out: get_time_series on one account or one \
product, one series per call. A missing value on a dated point is "not in yet", not zero. \
`aums` is the product's total assets under management, not one investor's balance.

Product Strategy, Domicile, Fee Structure: get_product (omit the name to walk the \
catalog in one request; slice with custom_field_names=['Strategy']). Those values are \
not on get_product_investors.

Product chain: resolve a product, then get_product_investors for who is in it (owners only, \
no figures), then get_time_series for the specific accounts in question. Do not iterate \
every account in a fund. Fund-level totals are get_time_series on the product's `aums`.

Subscriptions, redemptions, and share class: get_capital_flows with a mandatory date \
window. Scope with owner_id or account_ids from get_accounts_for_party / \
get_product_investors before the row cap — rows have no product, so join on account.id. \
Share class lives on the original subscription; the window must include that \
subscription date, not only the period you are asking about. A redemption with no \
account through originalSubscription is unattributed, not missing.

Meetings, calls, notes, emails, documents: search_activities first. That primary is an \
undocumented UI search and may 404 — that is not "no activity exists". Fall back to \
get_activity_history (party-scoped only), then get_activity_detail for the full \
untruncated body and the attachment list. Prefer search_activities with include_description \
for note text while the primary answers. Do not look for those on get_person / \
get_organization.

Firm-wide pipeline: look up a colleague's login with list_system_users, then \
search_opportunities. filter[representative.name] takes that login, not a display name. \
A disabled login returning empty is not "no coverage". One party's deals: \
get_opportunities (cheap; do not walk the firm for that). `previous_stage` is the stage \
the deal just left, not where it is now.

Open follow-ups: get_tasks_for_party. Both entity filters are required; status is \
client-side.

Custom-field names and types: list_custom_fields. Read party values through \
get_organization / get_person, product values through get_product, not through \
people-for-party.
"""
