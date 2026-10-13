INSTRUCTIONS = """
## Kyckr company verification workflow

- Start with `search_companies` and use the returned `id` as `kyckr_id` for later calls.
- Prefer `iso_code` plus `company_number` for a deterministic jurisdiction search.
- Use `get_enhanced_profile` for directors, representatives, and beneficial owners.
- Fall back to `get_lite_profile` when the jurisdiction does not support the enhanced profile.
- Use `list_company_documents` and `create_document_order` only when profile data is insufficient.
- Poll `get_order` while an order is `Pending`; the JSON document is inlined when available.
- Do not expose or repeat raw Kyckr download URLs.
- Search is free; profile and document calls can consume credits.
""".strip()
