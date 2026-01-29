# Unique GraphQL Stateful Mock Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement a schema-backed, stateful injected GraphQL mock client for the SharePoint connector tests, using official SDL snapshots from node-ingestion and node-scope-management.

**Architecture:** Commit SDL snapshots per service; create a mock engine that validates operations against the correct schema, dispatches to simple stateful handlers, and plugs into existing Nest test overrides (`INGESTION_CLIENT`, `SCOPE_MANAGEMENT_CLIENT`).

**Tech Stack:** TypeScript, `graphql` (execution + validation), `@graphql-tools/schema` (SDL → schema), Vitest.

---

### Task 1: Add schema snapshots to the connector repo

**Files:**
- Create: `services/sharepoint-connector/test/unique-schema/node-ingestion.schema.graphql`
- Create: `services/sharepoint-connector/test/unique-schema/node-scope-management.schema.graphql`

**Step 1: Copy node-ingestion SDL**
- Source (monorepo): `../monorepo/next/services/node-ingestion/src/@generated/schema.graphql`
- Destination (connectors): `services/sharepoint-connector/test/unique-schema/node-ingestion.schema.graphql`

**Step 2: Copy node-scope-management SDL**
- Source (monorepo): `../monorepo/next/services/node-scope-management/src/@generated/schema.graphql`
- Destination (connectors): `services/sharepoint-connector/test/unique-schema/node-scope-management.schema.graphql`

---

### Task 2: Create the stateful mock engine

**Files:**
- Create: `services/sharepoint-connector/test/test-utils/unique-stateful-mock/unique-mock.store.ts`
- Create: `services/sharepoint-connector/test/test-utils/unique-stateful-mock/unique-mock.engine.ts`
- Create: `services/sharepoint-connector/test/test-utils/unique-stateful-mock/unique-mock.handlers.ts`
- Create: `services/sharepoint-connector/test/test-utils/unique-stateful-mock/index.ts`

**Step 1: Define the store**
- Use maps keyed by id/key for fast lookups:
  - `scopes`, `contents`, `groups`, `users`
  - access control lists as sets/arrays as needed
- Provide `seed(initialState)` helper to load the scenario state.

**Step 2: Load schemas from the SDL snapshots**
- Use `buildSchema` (graphql) or `makeExecutableSchema` (graphql-tools) to build:
  - `ingestionSchema`
  - `scopeManagementSchema`

**Step 3: Implement request()**
- Parse the incoming `document` into a string (support string + DocumentNode)
- Extract operationName (regex from the document string is acceptable)
- Parse + validate using the standard `graphql` library:
  - `parse()` to parse the document
  - `validate()` to validate against the correct schema
- Validate document against the correct schema:
  - ingestion operations validated against `ingestionSchema`
  - scope-management operations validated against `scopeManagementSchema`
- Dispatch to `handlers[operationName]`
- Return the handler’s `data` payload
- Throw on:
  - validation errors
  - missing handler

**Step 4: Add call tracking**
- Wrap `request` with `vi.fn` so existing `getGraphQLOperations()`-style assertions continue to work (useful for request-payload assertions).
- Also expose the mock store from the engine so tests can prefer **store-based assertions** for most cases (more robust than asserting on call order/batching), keeping call assertions only when validating the request payload is the goal.

---

### Task 3: Implement minimal handlers needed by current tests

**Files:**
- Modify: `services/sharepoint-connector/test/test-utils/unique-stateful-mock/unique-mock.handlers.ts`
- Modify: `services/sharepoint-connector/test/sharepoint-sync.e2e-spec.ts`

**Step 1: Start with handlers used by `sharepoint-sync.e2e-spec.ts`**
- Ingestion:
  - `ContentUpsert` (mutate/store content; return `contentUpsert`)
  - `PaginatedContent` (filter from store; return `paginatedContent`)
  - `CreateFileAccessesForContents` / `RemoveFileAccessesForContents` (mutate access lists)
- Scope-management:
  - `PaginatedScope` (query scopes)
  - `UpdateScope` (mutate scope.externalId)
  - group/user operations if those tests cover them

**Step 2: Make “unhandled operation” failure message actionable**
- Include operationName
- Include which target (ingestion vs scope-management)
- Include a hint pointing to the handlers file

---

### Task 4: Replace `MockUniqueGraphqlClient` usage in tests

**Files:**
- Modify: `services/sharepoint-connector/test/sharepoint-sync.e2e-spec.ts`
- Modify or delete later: `services/sharepoint-connector/test/test-utils/mock-unique-graphql.client.ts`

**Step 1: Build scenario state at the start of each test**
- Follow the explicit state-first style from `services/sharepoint-connector/test/test brainsstorm.md`
  - Define both SharePoint and Unique state inline in the test
  - Pass that state into a helper like `runSynchronisation(state)` (or directly into the mock engine `seed(state)`), so the scenario is fully visible in the test body

**Step 2: Override Nest providers using new clients**
- `overrideProvider(INGESTION_CLIENT).useValue(ingestionClient)`
- `overrideProvider(SCOPE_MANAGEMENT_CLIENT).useValue(scopeManagementClient)`

**Step 3: Keep existing assertion helpers**
- Ensure the new client exposes `.request.mock.calls` compatibility (via `vi.fn`)

---

### Task 5: Verification

**Step 1: Run targeted tests**
- Run: `pnpm -C services/sharepoint-connector test` (or the repo’s preferred vitest command)
- Expected: existing e2e tests pass; failures should point to unhandled operations/validation mismatches.

**Step 2: Run repo check-all (per team rule)**
- Run: `npm run check-all`
- Expected: formatting + types pass.

