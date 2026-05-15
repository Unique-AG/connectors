export const serverInstructions = `
## Tool Selection Guidelines for Kyckr MCP

### Company lookup flow
- Start with \`search_companies\` to obtain the Kyckr company id. Prefer \`isoCode + companyNumber\` for deterministic results; name search may return many candidates and require disambiguation.
- Use \`get_enhanced_profile\` first for structured director/shareholder data. Fall back to \`get_lite_profile\` when the jurisdiction returns 405 for enhanced profiles.
- Only call \`list_company_documents\`, \`create_document_order\`, and \`get_order\` when structured profile data is insufficient or an official PDF is needed as evidence.

### Credit usage
- \`search_companies\` is free. Profile and document calls may spend Kyckr credits.
- Do not call paid endpoints speculatively. Confirm the company identity with search before ordering profiles or documents.
- \`create_document_order\` explicitly spends credits. Always confirm intent before calling it.

### Document polling
- Kyckr has no webhooks. After \`create_document_order\`, poll with \`get_order\` until the order reaches a terminal state.
- Use \`list_orders\` to reconcile recently created orders when a specific orderId is not in context.

### Customer reference
- Pass \`customerReference\` on every call that supports it so usage can be reconciled to the correct customer or case.
`;
