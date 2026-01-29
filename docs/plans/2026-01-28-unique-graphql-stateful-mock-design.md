# Unique GraphQL Stateful Mock (Schema-Backed) — Design

**Goal:** Replace static GraphQL fixtures with a stateful, schema-validated injected mock client for the SharePoint connector tests, using the official GraphQL schemas from node-ingestion and node-scope-management.

## Where we get the schemas (in this workspace)

The official SDL schemas are available in the monorepo as generated artifacts:

- **node-ingestion**: `unique/monorepo/next/services/node-ingestion/src/@generated/schema.graphql`
- **node-scope-management**: `unique/monorepo/next/services/node-scope-management/src/@generated/schema.graphql`

These are the schemas we snapshot into the SharePoint connector repo so tests don’t depend on the monorepo checkout.

## Architecture (high level)

### Components

- **Schema snapshots (committed)**
  - `services/sharepoint-connector/test/unique-schema/node-ingestion.schema.graphql`
  - `services/sharepoint-connector/test/unique-schema/node-scope-management.schema.graphql`

- **Stateful mock engine**
  - Builds a `GraphQLSchema` from each SDL snapshot.
  - Exposes two injected clients (`ingestionClient`, `scopeManagementClient`) implementing:
    - `request(document: RequestDocument, variables?: Variables): Promise<T>`
  - Maintains a **mutable in-memory store** seeded per test scenario.

- **Operation handlers (“resolvers”)**
  - A map of `operationName -> handler`.
  - Each handler can:
    - Read/query from the store (filtering, lookups)
    - Mutate the store (upserts, access changes, etc.)
    - Return a payload matching the operation’s top-level `data` shape

### Data flow

1. Each test builds an explicit scenario state up front (your `test brainsstorm.md` style: SharePoint tree + Unique entities).
2. Each test loads that state into the mock engine (either by constructing a fresh engine from the state, or by calling `seed(state)` on a reusable engine).
3. Test overrides Nest providers (`INGESTION_CLIENT`, `SCOPE_MANAGEMENT_CLIENT`) with the injected mock clients.
3. Production code calls `client.request(document, variables)`.
4. Mock engine:
   - extracts `operationName`
   - parses and **validates** the document against the correct service schema (ingestion vs scope-management)
     - use the standard `graphql` library: `parse()` + `validate()`
     - schema construction from SDL can use `graphql` or `@graphql-tools/schema` (optional)
   - dispatches to `handlers[operationName]`
5. Handler returns `data` payload; engine returns it to the production code.

## Error handling / safety

- **Validation failure** (document no longer matches schema): throw with GraphQL validation errors.
- **Unhandled operation** (new call added but no handler): throw a clear error listing the operationName.

## Testing strategy (recommended)

- **Keep call tracking**: wrap `.request` in `vi.fn` so tests can assert request payloads (`variables`) with the existing `getGraphQLOperations()` style (as done today in `sharepoint-sync.e2e-spec.ts`).
- **Prefer store assertions over time**: for most tests, assert on the **mock store state** (e.g., which content/scope/access records exist after sync). This fits well when each test constructs the full scenario state explicitly, then runs the sync.
  - Keep call assertions for the cases where verifying the exact request payload is the purpose of the test.

## Schema update workflow

Because schemas are official snapshots:

- When the real services change schema, update the snapshots in:
  - `services/sharepoint-connector/test/unique-schema/*.schema.graphql`
- When the connector adds a new GraphQL operation:
  - schema snapshot likely already contains it (if it exists in the real service)
  - tests will fail with “Unhandled operation” until a handler is added

## Non-goals

- Implementing full Unique business logic.
- Modeling every type/field in the schema with custom resolvers; we only implement the operations the connector uses.

