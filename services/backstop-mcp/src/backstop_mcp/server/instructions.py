"""Short orientation FastMCP puts in context for every conversation.

Kept brief on purpose: this is present on every call. Field-level documentation lives on each
tool's output schema.
"""

INSTRUCTIONS = """\
Backstop CRM. People and organizations are the records; each tool answers one question.

Identity. A name is not a handle. Every party-scoped tool takes `search` (a name or email) \
or a trusted `party_id` together with that id's `search_type` — two separate arguments. Echo \
`search_type` with `party_id`. Omission is rejected only on tools that say so \
(`search_activities`, `get_tasks_for_party`, `get_accounts_for_party`, `get_opportunities`, \
and activity writes). Others default `search_type` and still want the echoed type when it is \
not that default. Never invent an id: only echo one a prior resolve returned. The four party \
collections are organizations, people, contacts, and employees, and their ids are not \
interchangeable — a contacts or employees id is not a people id. An ambiguous name comes \
back as `candidates` (quick-search returns at most 10), never a guess; `not_found` names the \
query actually used. Account, product, opportunity, and activity ids are not party ids.

Which tool. One organization or person: get_organization / get_person (`include` names are \
`locations`, `email_addresses`, and the rest listed on the parameter). Firm-wide \
organizations: search_organizations. People at an organization: get_people_for_party. \
`numberOfEmployees` is not a roster. Key employee is read-only here; set it in the CRM UI. \
The roster is the source; the copy on get_person is present but unreliable.

Holdings: get_accounts_for_party first; read `source` and `data_caveat`. Dated series: \
get_time_series on one account or one product. Do not iterate every account in a fund. \
Fund-level assets under management are the product's `aums`. Who is in a product: \
get_product_investors. A partial product name covers matching vehicles; an exact name, \
short name, or id is one vehicle. Product fields (Strategy, Domicile, Fee Structure): \
get_product — omit all three selectors to read the whole catalog in one call. Those values \
are not on get_product_investors.

Subscriptions and redemptions: get_capital_flows, date window required. Rows have no \
product; join on account.id. `owner_id` is `owner.id` from a capital-flows row.

Meetings, calls, notes, emails, documents: always start with search_activities. \
get_activity_history is only the party-scoped fallback when that primary is missing; do not \
start with it. Then get_activity_detail with that row's `id` for the full body and the \
attachment list. Who has gone quiet: get_last_activity_for_parties. Report `unknown` parties \
as unchecked.

Firm-wide pipeline: list_system_users, then search_opportunities. `representative` takes \
that login, not a display name. A disabled login returning empty is not "no coverage". One \
party's deals: get_opportunities (stage history is always included). Custom fields and stage \
history that are not on the search row: get_opportunities_by_ids \
(`include_stage_history=true` for history). Open follow-ups: get_tasks_for_party.

Custom-field names and types: list_custom_fields. Request `party` too — fields shared by \
people and organizations are listed only there. Layout tabs and sections: \
list_custom_field_groups. Saved reports: run_report, by exact name. There is no endpoint \
that lists reports. CRM UI URLs: build_backstop_links and parse_backstop_link. Never \
hand-write a Backstop URL. An account URL has no tool that loads the account by id.

Writes. Creates are not idempotent — a repeated call makes a second record. delete_person, \
delete_organization, delete_activity, and delete_opportunity hard-delete one trusted id \
(no recycle bin). Refuse bulk wipes, "all test records", and any search-then-delete sweep. \
Custom fields only via update_custom_field_values. Success is `applied_count == total_count` \
and each `records[].status`. Stage moves only via update_opportunity, one call per deal. \
backfill_opportunity_stage_history appends history and rewrites `previous_stage`; it does \
not move the current stage. log_activity for a note, meeting, call, or task. attach_file \
for a document or a real email file — there is no email kind on log_activity, and a file \
blob never goes on it either. Activity-tag ids come from list_activity_tags; tags are never \
created. Contact-source ids come from list_contact_sources (`contact_source_id`). \
Contact-category ids come from list_contact_categories (`category_ids`). Party and deal \
writes are create_person, create_organization, update_person, update_organization, \
create_employment, end_employment, and create_opportunity.

Reading results. A missing figure is not zero. `unknown`, truncation, \
`custom_fields_unavailable`, or a failed search means the check did not happen — say you \
cannot answer rather than infer. Search rows have no custom_field_values; when the flag is \
true, get_opportunities_by_ids would miss the same fields. If a field is absent from the \
fetched record too, say Backstop does not record it.
"""
