# PR Proposal

## Ticket

UN-23680

## Title

feat(backstop-mcp,main): pull contact details and opportunities, and describe what we return

## Description

- Add a curated include registry (`features/includes/`) so `get_person` / `get_organization` can
  side-load `locations`, `email_addresses`, `primary_contact` (org), `company` (person) and
  `representative` in the same request. The registry is the allowlist — `include=activities`
  side-loads 355 resources regardless of `page[limit]`, so unbounded relationships are unreachable
  by construction, and the include names are ours because Backstop's `emails` relationship is 488
  email *messages*, not addresses.
- Project side-loaded resources into documented domain models rather than passing Backstop's
  envelope through. `contactEmails` keeps its `retired` flag: one test contact has three addresses,
  two retired, one of them another firm's — so retired entries are returned and labelled, never
  silently dropped or silently offered.
- Add `get_opportunities`: resolves a party like `get_activity_history`, then one call to
  `/{segment}/{id}/opportunities?include=stage,stageHistory` plus a TTL-cached
  `GET /opportunity-stages`. `filter[isOpen]` returns 400 and `sort=` is silently ignored on party
  sub-collections, so open/closed filtering and recency ordering are done in memory — safe because
  the largest party in the instance has 33 opportunities and none exceeds 50. No cursor is exposed;
  paging outward would let an open-only query return an authoritative-looking empty page.
- Surface the current stage correctly. `stage` is a relationship, while the `previousStage`
  attribute names the stage a deal just *left* and is absent until it has moved — so a payload
  without `include=stage` cannot name the current stage and would mislead. Stage history is
  included, with its inline `{resourceType, resourceId, resourceLink}` pointers resolved against
  `included` and then the 7-row vocabulary (3 of 6 referenced stages arrive in neither otherwise).
- Make the returned entities self-describing: all seven tools return typed models so FastMCP
  publishes `outputSchema` with every field description, a new `describe_data_model` tool renders the
  registry plus a tool-ownership map and the stage vocabulary, and `FastMCP(instructions=…)` carries
  a short orientation. `results.py` is deleted (`tool_error` had zero call sites); an `OmitNoneModel`
  base preserves `get_activity_history`'s absent-vs-null semantics under typed returns.
