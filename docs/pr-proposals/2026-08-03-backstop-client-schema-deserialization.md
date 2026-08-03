# PR Proposal

## Ticket
UN-22647

## Title
feat(backstop-mcp): add schema-validated deserialization to BackstopClient

## Description
- `BackstopClient.get/post/patch/delete/paginate` now take a frozen, generic `Request[T]` object with an optional `schema` field instead of loose keyword args; passing a schema returns a validated model (`T`) instead of a raw `dict[str, object]`, with `schema=None` preserving today's behavior exactly.
- `PageResult` becomes generic (`PageResult[T]`) so `paginate()` can return typed items the same way, validated per-item after the existing JSON:API envelope parsing.
- New `BackstopResponseSchemaError` wraps `pydantic.ValidationError` on a schema mismatch, carrying the request path and schema name, and is logged where today's bare validation failures aren't.
- Scoped to `backstop_client/` only — caller migrations (`party_resolver/search.py`, `tools/get_organization.py`) land separately when `UN-23676--party-id-resolver` rebases onto this branch.
