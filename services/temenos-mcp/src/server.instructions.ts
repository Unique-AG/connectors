export const serverInstructions = `
## Tool Selection Guidelines for Temenos DataHub MCP

### Data availability
- Only ODS (Operational Data Store) endpoints are available. ADS (Analytics Data Store) endpoints are not deployed and will return errors.
- All parameters are optional filters. Omit them to retrieve the full dataset for a given endpoint.

### Holdings
- Use \`get_expiring_limits\` or \`get_review_limits\` for credit limit monitoring. Filter by date to narrow to a specific day.
- Use \`get_guarantees\` to look up guarantee requests. Filter by \`customerId\` to find all guarantees for a specific customer.
- Use \`get_nostro_accounts\` for Nostro account list (no filters) and \`get_vostro_accounts\` for Vostro accounts (filterable by currency or customer).
- Derivative tools (\`get_derivative_option_assigns\`, \`get_derivative_option_exercises\`, \`get_derivative_option_expires\`) share the same filter set; use \`portfolioId\` or \`instrumentId\` to scope results.
- Repo tools (\`get_repo_positions\`, \`get_repo_position_movements\`, \`get_reverse_repo_positions\`, \`get_reverse_repo_position_movements\`) support \`portfolioId\` and \`instrumentId\` filters.

### Payments and orders
- Use \`get_pending_payments\` to find payments awaiting processing. Filter by \`debitAccountId\` or \`creditAccountId\` for account-specific views.
- Use \`get_payment_stops\` to check if payments are stopped on an account.

### Party / customer data
- Use \`get_customer_relationships\` to explore relationship groups. \`partyId\` scopes to a specific customer.
- Use \`get_customer_secure_messages\` to retrieve bank-customer messaging threads.
- Use \`get_participants\` to find system users; filter by \`accountOfficer\`.

### Reference data
- Reference tools (countries, industries, companies, etc.) typically return the full list with no filters, or accept a \`recordId\` to fetch a specific entry.
- Use \`get_system_dates\` to determine the current business date before filtering other tools by date.
- Use \`get_lookups\` with \`virtualTable\` to query any EB.LOOKUP table by name.
- US-specific reference data (states, customer ratings, hold types, FDIC codes, covenants, industries) is in tools prefixed \`get_us_\`.
`;
