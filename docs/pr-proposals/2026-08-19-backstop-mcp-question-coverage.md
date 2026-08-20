# PR Proposal

## Title
feat(backstop-mcp): cover the IR team's question list with tags, resolved custom fields and firm-wide reads

## Description
- Adds nine tools — `list_activity_tags`, `list_custom_field_groups`, `find_activities`,
  `get_product_investors`, `find_opportunities`, `get_capital_flows`, `get_tasks_for_party`,
  `list_system_users`, `run_report` — covering the topic, product-side and firm-wide axes no existing
  tool had.
- Enhances the ten shipped tools: activity tags, attendees and `regarding` on the timeline; resolved
  and sliceable custom-field values on party reads; account performance (`irrs`, `returns`,
  `percentageOfFundHistory`) and tenure dates; balances on a party's accounts.
- Collapses `get_product_positions` from up to ~1500 sub-requests per call to a single paginated walk
  by side-loading the account series, and fixes the ~4× duplication in `list_custom_fields`.
- Firm-wide reads project rather than relay: sparse fieldsets on the wire, caller-selected fields out,
  row caps, an aggregate mode, and explicit scan-coverage and truncation reporting.
- Excludes cohort questions needing predicates over all organizations or people (14 questions,
  reasoning in `docs/backstop-mcp-cohort-questions.md`), plus write-back and dashboard arithmetic.

## Notes
- `.gitcommitizen` has `enforce-patterns = true` and no scope matching `docs/plans/` or
  `docs/pr-proposals/`. The design docs need either a new scope or a home under
  `services/backstop-mcp/docs/` before they can be committed alongside this work.
- No Jira ticket is linked yet; these tasks should be reconciled against the existing UN-236xx
  sub-tasks first.
