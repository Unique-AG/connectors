# Kyckr MCP Implementation Scope

This document summarizes the intended scope for the first `kyckr-mcp` implementation. It is based on:

- `kyckr-mcp-kyckoff.txt`
- `kyckr-demo-flow-in-postman-summary.txt`
- `kyckr-v2-api-documentation.yaml`

## Goal

Build a thin TypeScript MCP service that exposes Kyckr company registry data as MCP tools for a KYC/KYB demo flow.

The service should wrap Kyckr's REST API directly. It should not contain business workflow logic for the final KYC report. Ricardo's higher-level agent/script flow will decide which company data is needed and when to call the MCP tools.

The immediate target is a demo, not a production-grade rollout. It should work against the Kyckr sandbox/test API first and be simple enough to evolve later.

## Product Context

Kyckr provides a normalized API layer over many national company registries. The relevant KYC/KYB use case is to corroborate claims in a source-of-wealth or company ownership investigation, for example:

- Does a company exist?
- Is the company active?
- Who are the directors or company officials?
- Who are the shareholders or beneficial owners where registry data provides them?
- Are there official registry documents that can be ordered for evidence or missing details?

Kyckr is not intended for bulk ingestion into a vector store. The expected usage is targeted, on-demand retrieval once the company being investigated is known.

## Service Shape

The starting point is the copied `outlook-semantic-mcp` service, renamed to `kyckr-mcp`.

Use the templates and service patterns laid out by `outlook-semantic-mcp` when building this service. The goal is not to invent a new MCP architecture, but to reuse the existing NestJS/MCP structure, configuration style, tool-registration approach, logging conventions, Docker/deploy shape, and local development patterns where they still make sense after simplification.

For the first Kyckr version, strip the copied service down aggressively:

- Remove database usage, migrations, Drizzle schema, and any persistence-dependent code.
- Remove AMQP, queue workers, ingestion flows, subscriptions, and sync logic.
- Remove Microsoft/Outlook authentication and delegated access flows.
- Remove Outlook-specific controllers, services, tools, prompts, and domain models.
- Keep only the minimum NestJS/MCP HTTP server structure needed to expose MCP tools.
- Keep standard config, minimal logging, minimal metrics, Docker/deploy scaffolding, and health checks if they do not pull in unnecessary dependencies.

The result should be a simple MCP wrapper around Kyckr's REST API, not an Outlook-style ingestion service.

## Minimal Logging And Metrics

Include a small observability baseline from the beginning. This should stay simple and should reuse the `outlook-semantic-mcp` conventions where practical.

Logging should cover:

- Service startup and selected Kyckr base URL, without secrets.
- Incoming MCP tool calls by tool name.
- Outgoing Kyckr API calls by method and path, without sensitive headers.
- Kyckr API failures with status code, details, and correlation id where present.
- Document order creation and order polling status, without logging downloaded document contents.

Metrics should cover:

- Total MCP tool calls by tool name and result.
- Kyckr API request count by method, path, and status code.
- Kyckr API request duration.
- Document order status counts where easy to capture.

Do not add complex dashboards, alerts, tracing, or production SLO work for the first version. The goal is enough logs and metrics to debug the demo and understand whether calls are succeeding.

## Authentication And Access

Kyckr API authentication is a single bearer/API key credential. There is no OAuth flow with Kyckr.

For the demo:

- Store the Kyckr API key in service configuration or secrets.
- Call Kyckr with `Authorization: Bearer <key>`.
- Use the Kyckr test base URL first: `https://test-api.kyckr.com/v2`.
- Keep production configurable via base URL: `https://api.kyckr.com/v2`.

Access to the MCP endpoint itself is a separate concern. The kickoff discussion accepted a pragmatic demo approach:

- No full OAuth/Zitadel integration for the first version.
- Protect the MCP endpoint with a simple shared secret/token if needed.
- One discussed shape was a secret in the MCP URL path before `/mcp`, validated by the service.
- Longer-term access control needs a product decision, because Unique already controls which spaces can use configured MCP servers.

Do not bake real credentials into code or docs.

## Kyckr API Flow

The normal flow is:

1. Search for a company with `GET /companies`.
2. Use the returned Kyckr company id, for example `GB|MTE2NTUyOTA`.
3. Retrieve a lite or enhanced profile.
4. If profile data is insufficient, list available documents.
5. Order a document.
6. Poll order status until the document is ready.

Country-specific search is preferred. Kyckr supports global search when `isoCode` is omitted, but global search uses stored data. Once the country is known, the integration should confirm the company with a country-specific search.

Company-number search is preferred for automation because it usually returns one precise match. Name search can return many candidates and may need agent/user disambiguation.

## Proposed MCP Tools

Keep tools close to Kyckr's REST resources. Avoid hiding too much workflow logic inside the MCP server.

### `search_companies`

Wraps `GET /companies`.

Inputs:

- `isoCode?: string`
- `name?: string`
- `companyNumber?: string`

Rules:

- Require at least one of `name` or `companyNumber`.
- Prefer `isoCode + companyNumber` for deterministic automated flows.
- Return the Kyckr `id`, company name, company number, status, type, address, and start date where available.

### `get_lite_profile`

Wraps `GET /companies/{kyckrId}/lite`.

Inputs:

- `kyckrId: string`
- `customerReference?: string`

Purpose:

- Retrieves basic verified company details.
- Useful when enhanced profiles are unavailable or unnecessary.

Typical returned data includes company name, company number, registered address, registration/foundation date, legal status, legal form, activity, and registration authority.

### `get_enhanced_profile`

Wraps `GET /companies/{kyckrId}/enhanced`.

Inputs:

- `kyckrId: string`
- `customerReference?: string`
- `showDirectorships?: boolean`
- `extend?: string`

Purpose:

- Retrieves the main company profile, including directors/company officials, shareholders, share capital, and UBO information where the registry provides structured data.

Notes:

- `showDirectorships` is currently relevant for GB/UK where supported.
- `extend=geocoding` may be available only for entitled accounts and can add cost.
- Some jurisdictions may return `405` for synchronous enhanced profiles; async enhanced profile ordering is documented as "coming soon", so do not treat it as core MVP unless the sandbox proves it works.

### `list_company_documents`

Wraps `GET /companies/{kyckrId}/documents`.

Inputs:

- `kyckrId: string`
- `customerReference?: string`
- `continuationKey?: string`

Purpose:

- Lists registry documents available for a company.
- Used when directors/shareholders are not available through structured profile APIs or when an official PDF is needed as audit evidence.

Return document id/product id, document name/description, cost, delivery estimate, and continuation key where available.

### `create_document_order`

Wraps `POST /orders`.

Inputs:

- `kyckrId: string`
- `productId: string`
- `customerReference?: string`
- `contactEmail?: string`

Purpose:

- Orders a selected document.
- Returns order id, status, and customer reference.

This is the main paid/asynchronous action in the first version. Make the tool description explicit that it can spend Kyckr credits.

### `get_order`

Wraps `GET /orders/{orderId}`.

Inputs:

- `orderId: string`

Purpose:

- Polls a specific order until it reaches a terminal state.
- On success, the Kyckr response should include retrieval/download details for the document.

### `list_orders`

Wraps `GET /orders`.

Inputs:

- `startDate?: string`
- `endDate?: string`
- `isoCode?: string`

Purpose:

- Supports polling/reconciliation across multiple orders.
- Useful because Kyckr has no webhook support yet.
- Lets the agent check recently created/completed orders by date range if it does not have a specific `orderId` in context.

## Error And Edge Case Expectations

The MCP tools should surface Kyckr errors clearly rather than swallowing them.

Important cases:

- `400`: missing or invalid parameters.
- `401`: Kyckr API key missing or invalid.
- `403`: feature not available for the account.
- `404`: company/order not found.
- `405`: synchronous enhanced profile unavailable for the jurisdiction.
- `429`: rate limit exceeded. The API docs mention 50 requests per 10 minutes.

Registry availability and response richness vary heavily by country. Some registries provide rich structured directors/shareholders; others may only verify existence/status or require document orders.

Document delivery can be immediate, minutes, hours, or longer depending on the jurisdiction. There are no webhooks, so callers must poll.

## Cost And Customer Reference

Kyckr uses credits. Search is free, while profiles and documents can cost credits. Expensive jurisdictions/documents should not be called speculatively.

Pass `customerReference` through where supported so usage can be reconciled to a customer, case, or transaction. This is especially important in a reseller or multi-tenant Unique deployment where one Kyckr key may serve multiple end customers.

## Sandbox Notes

Kyckr's sandbox is simulated because national registries usually do not provide sandboxes.

Important limitations:

- It contains a limited set of representative companies.
- Name search in sandbox may return all companies in a country rather than realistic ranked search results.
- Company-number search is the recommended test path.
- It is suitable for validating request/response shape, not high-volume or realistic registry behavior.

## Non-Goals For The First Version

- No database or persistence.
- No AMQP, subscriptions, ingestion, or sync workers.
- No vector-store ingestion of Kyckr data.
- No country capability matrix unless manually encoded later.
- No full OAuth implementation for MCP endpoint access.
- No high-level KYC reasoning, red-flag analysis, or report generation inside the MCP server.
- No automated document selection logic beyond exposing available documents clearly.
- No production readiness guarantees before a follow-up hardening pass.

## Implementation Priorities

1. Strip the copied service down to a minimal MCP/NestJS template.
2. Add Kyckr config: base URL, API key, optional MCP access token, optional default customer reference/contact email.
3. Implement a small Kyckr HTTP client with typed request parameters and transparent error handling.
4. Expose the core MCP tools: search, lite profile, enhanced profile, list documents, create order, get order, list orders.
5. Validate tool schemas and descriptions so an LLM understands when each tool spends credits or may require polling.
6. Test manually against sandbox credentials from 1Password.
7. Keep the code structured enough that a production pass can later add proper MCP endpoint auth, deployment hardening, observability, and country-specific guidance.

## Implementation Handoff Checklist

The implementing agent should treat this as a focused service simplification plus Kyckr wrapper task.

Expected first-version MCP tools: exactly 7.

- `search_companies`
- `get_lite_profile`
- `get_enhanced_profile`
- `list_company_documents`
- `create_document_order`
- `get_order`
- `list_orders`

Suggested configuration names:

- `KYCKR_API_BASE_URL`, defaulting to `https://test-api.kyckr.com/v2` for local/demo use.
- `KYCKR_API_KEY`, required.
- `MCP_ACCESS_TOKEN`, optional demo protection for the MCP endpoint.
- `KYCKR_DEFAULT_CUSTOMER_REFERENCE`, optional.
- `KYCKR_DEFAULT_CONTACT_EMAIL`, optional.

Acceptance criteria:

- The copied Outlook service no longer contains active Outlook, Microsoft Graph, database, AMQP, ingestion, subscription, or delegated-auth behavior.
- The service starts locally as a minimal MCP server.
- The MCP endpoint exposes the 7 Kyckr tools above.
- Each tool delegates to the matching Kyckr REST endpoint and returns the Kyckr response in a form useful to an LLM.
- Paid or asynchronous tools have clear descriptions warning about credits and polling.
- Kyckr API errors are surfaced with status code, message/details, and correlation id where present.
- Minimal logs and metrics exist for tool calls, Kyckr API calls, errors, durations, and document order status.
- No real Kyckr credentials are committed.
- Manual sandbox testing is documented in the implementation notes or PR description.

## Open Questions

- Exact deployment target for the demo service.
- Exact MCP endpoint access-token shape and whether the token belongs in URL path, query, or header.
- Whether `POST /companies/{kyckrId}/enhanced` works in the current sandbox despite being marked "coming soon".
- Which `customerReference` format Ricardo wants for demo cases.
- Which countries/companies should be used for the first end-to-end demo path.
