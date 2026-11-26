INSTRUCTIONS = """
## Kyckr company verification workflow

### Company lookup
- Start with `search_companies` and use the returned `id` as `kyckr_id` for later calls.
- Prefer `iso_code` plus `company_number` for a deterministic jurisdiction search. Name search can
  return many candidates and needs disambiguation.
- Use `get_enhanced_profile` first for directors, representatives, and beneficial owners. Fall back
  to `get_lite_profile` when the jurisdiction returns 405 for enhanced profiles.
- Use `list_company_documents`, `create_document_order`, and `get_order` only when profile data is
  insufficient or an official document is needed as evidence.

### Credit usage
- `search_companies` is free. Profile and document ordering calls can spend Kyckr credits.
- Do not call paid endpoints speculatively. Confirm the company identity with a search first.
- Call `create_document_order` only after the user has approved the document and the credit cost
  shown by `list_company_documents`. Naming a filing is not approval.

### Document polling and presentation
- After `create_document_order`, inspect `data.status`. On `Success` the document arrives with the
  same call. On `Pending`, poll `get_order` until `Success` or `Failed`.
- Render `data.documentJson` to the user as a structured, readable summary. It is the document.
- When `data.documentJson` is absent at `Success`, relay the PDF-only message in `details`.
- Never expose or repeat raw Kyckr download URLs or order-internal links.
- Use `list_orders` to reconcile recent orders when an order id is not in context.

### Failed calls
- A call Kyckr refuses fails with `Kyckr answered <status>`, Kyckr's message and its correlation
  id. 400 is a bad parameter, 401 a problem with the server's Kyckr credential, 403 a feature the
  account lacks, 404 an unknown id, 405 an enhanced profile not available for that jurisdiction,
  410 an order that is gone for good (do not retry) and 429 a rate limit.
""".strip()
