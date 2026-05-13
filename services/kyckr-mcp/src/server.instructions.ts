export const serverInstructions = `
## Tool Selection Guidelines for Kyckr MCP

### Company lookup flow
- Start with \`search_companies\` to obtain the Kyckr company id. Prefer \`isoCode + companyNumber\` for deterministic results; name search may return many candidates and require disambiguation.
- Use \`get_enhanced_profile\` first for structured director/shareholder data. Fall back to \`get_lite_profile\` when the jurisdiction returns 405 for enhanced profiles.
- Only call \`list_company_documents\`, \`create_document_order\`, and \`get_order\` when structured profile data is insufficient or an official PDF is needed as evidence.

### Credit usage
- \`search_companies\` is free. Profile and document calls may spend Kyckr credits.
- Do not call paid endpoints speculatively. Confirm the company identity with search before ordering profiles or documents.
- Once the user has named or chosen a specific filing from \`list_company_documents\`, call \`create_document_order\` directly; do not stage a separate confirmation step (the cost is already known from \`list_company_documents\`).

### Document polling and presentation
- After \`create_document_order\`, inspect \`data.status\`. On \`Success\` the document body is delivered with the same call. On \`Pending\`, poll \`get_order\` until \`data.status\` is \`Success\` or \`Failed\`.
- Render \`data.documentJson\` to the user as a structured, readable summary - it IS the document.
- When \`data.documentJson\` is absent at \`Success\`, \`details\` carries the message that the document is PDF-only and PDF delivery is not yet supported (coming soon). Relay that message to the user.
- Never surface raw download URLs or order-internal links.
- Use \`list_orders\` to reconcile recently created orders when a specific orderId is not in context.

### Customer reference
- Pass \`customerReference\` on every call that supports it so usage can be reconciled to the correct customer or case.
`;
