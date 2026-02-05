# Design: Unified SharePoint Test Engine

## Problem

The SharePoint connector e2e tests currently use multiple separate mock implementations:

- `MockGraphClient` - Microsoft Graph API (fluent API pattern)
- `MockSharepointRestClientService` - SharePoint REST API
- `MockHttpClientService` - Generic HTTP client for file uploads
- `MockIngestionHttpClient` - Unique ingestion HTTP API (file-diff endpoint)
- `UniqueStatefulMock` - Stateful mock for Unique GraphQL clients

While `UniqueStatefulMock` follows a schema-validated, stateful pattern with operation handlers and a mutable store, the other mocks are simpler and don't share state. This leads to:

1. **Fragmented state** - Each mock maintains its own data, making it harder to set up coherent test scenarios
2. **Inconsistent patterns** - Different mocking approaches across clients
3. **Harder scenario setup** - Tests must configure multiple mocks independently

## Solution

### Overview

Create a unified `SharePointTestEngine` that orchestrates all mocks with a single shared state model. The engine provides:

1. **Single source of truth** - One mutable store containing SharePoint data, Unique data, and upload/request tracking
2. **Adapter pattern** - Each mock becomes a thin adapter that reads from/writes to the shared store
3. **Unified seeding** - One `seed()` call to set up complete test scenarios
4. **Consistent testing experience** - All mocks follow the same stateful pattern

### Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     SharePointTestEngine                            │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                   SharePointTestStore                        │   │
│  │                                                              │   │
│  │  SharePoint Data          │  Unique Data                    │   │
│  │  ─────────────────        │  ───────────                    │   │
│  │  • drives                 │  • users                        │   │
│  │  • driveItems             │  • groups                       │   │
│  │  • permissions            │  • scopes                       │   │
│  │  • siteLists              │  • contents                     │   │
│  │  • listItems              │                                 │   │
│  │  • groupMembers           │  HTTP Tracking                  │   │
│  │  • siteGroupMemberships   │  ─────────────                  │   │
│  │  • fileContents           │  • uploadedFiles                │   │
│  │                           │  • fileDiffResults              │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────────┐ │
│  │ GraphClient  │ │ SharePoint   │ │ HttpClient   │ │ Ingestion  │ │
│  │ Adapter      │ │ REST Adapter │ │ Adapter      │ │ HTTP Adapt │ │
│  └──────────────┘ └──────────────┘ └──────────────┘ └────────────┘ │
│                                                                     │
│  ┌──────────────────────────┐ ┌──────────────────────────────────┐ │
│  │ Ingestion GraphQL Client │ │ Scope Management GraphQL Client  │ │
│  │ (existing handlers)      │ │ (existing handlers)              │ │
│  └──────────────────────────┘ └──────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

**Components:**

1. **`SharePointTestStore`** - Single mutable store with all test state
2. **`GraphClientAdapter`** - Wraps store access in Microsoft Graph fluent API
3. **`SharepointRestAdapter`** - Wraps store access for REST endpoints
4. **`HttpClientAdapter`** - Tracks uploads, returns configurable responses
5. **`IngestionHttpAdapter`** - Returns file-diff results from store
6. **`UniqueGraphQLClients`** - Existing handlers integrated with unified store

**Factory Function:**

```typescript
function createSharePointTestEngine(options?: SharePointTestEngineOptions): SharePointTestEngine {
  const store = createSharePointTestStore();
  seedStore(store, defaultSeedState());
  if (options?.initialState) seedStore(store, options.initialState);
  
  return {
    store,
    graphClient: createGraphClientAdapter(store),
    sharepointRestClient: createSharepointRestAdapter(store),
    httpClient: createHttpClientAdapter(store),
    ingestionHttpClient: createIngestionHttpAdapter(store),
    ingestionGraphqlClient: createIngestionGraphqlClient(store),
    scopeManagementGraphqlClient: createScopeManagementGraphqlClient(store),
    seed: (state) => seedStore(store, state),
    reset: () => resetAndReseedStore(store, defaultSeedState(), options?.initialState),
  };
}
```

**Test Usage:**

```typescript
describe('SharePoint synchronization (e2e)', () => {
  let engine: SharePointTestEngine;

  beforeEach(async () => {
    engine = createSharePointTestEngine();

    const moduleFixture = await Test.createTestingModule({ imports: [AppModule] })
      .overrideProvider(GraphClientFactory).useValue({ createClient: () => engine.graphClient })
      .overrideProvider(SharepointRestClientService).useValue(engine.sharepointRestClient)
      .overrideProvider(HttpClientService).useValue(engine.httpClient)
      .overrideProvider(IngestionHttpClient).useValue(engine.ingestionHttpClient)
      .overrideProvider(INGESTION_CLIENT).useValue(engine.ingestionGraphqlClient)
      .overrideProvider(SCOPE_MANAGEMENT_CLIENT).useValue(engine.scopeManagementGraphqlClient)
      .compile();
  });

  describe('when file exceeds size limit', () => {
    beforeEach(() => {
      const item = engine.store.driveItems.get('item-1');
      if (item) item.size = 999999999;
    });

    it('does not store content', async () => {
      await service.synchronize();
      expect(engine.store.contents.size).toBe(0);
    });
  });
});
```

### Error Handling

**Unhandled Operations:**
```typescript
throw new Error(`SharePoint mock: unhandled Graph API URL "${url}". Add handler in graph-client.adapter.ts`);
```

**Missing Data:**
- Queries return empty arrays/objects (mimics real API)
- Mutations throw clear errors when required data is missing

**GraphQL Validation:**
- Continues to use SDL schema validation from `UniqueStatefulMock`

### Testing Strategy

**Behavioral tests only** - The e2e tests are the tests for this infrastructure.

**Assert on store state:**
```typescript
const storedContents = [...engine.store.contents.values()];
expect(storedContents).toHaveLength(1);
expect(storedContents[0].title).toBe('test.pdf');
```

**Request tracking when needed:**
```typescript
const fileDiffCalls = engine.getHttpCalls('/v2/content/file-diff');
expect(fileDiffCalls[0].body.sourceKind).toBe('MICROSOFT_365_SHAREPOINT');
```

## Out of Scope

- Full Microsoft Graph API validation (no OpenAPI schema validation)
- Pagination support for Graph API mocks (tests use small datasets)
- Real file content handling (mock file content is sufficient)
- Multi-site support in single test (one site per test is enough)
- Error simulation framework (tests can mutate store/responses directly)
- Async/event-driven state changes (synchronous is sufficient)

## Tasks

1. **Create unified store module** - Define `SharePointTestStore` interface and `createSharePointTestStore()`, `resetStore()`, `seedStore()` functions. This is the single source of truth for all test state.

2. **Create Graph client adapter** - Refactor `MockGraphClient` to read from/write to the unified store instead of its own internal state. Keep the fluent API pattern.

3. **Create SharePoint REST adapter** - Refactor `MockSharepointRestClientService` to read from the unified store for group memberships.

4. **Create HTTP client adapter** - Refactor `MockHttpClientService` to track uploads in the unified store and return configurable responses.

5. **Create Ingestion HTTP adapter** - Refactor `MockIngestionHttpClient` to return file-diff results from the unified store and track requests.

6. **Integrate UniqueStatefulMock into unified store** - Either merge the existing `UniqueMockStore` into `SharePointTestStore` or create a composed store that wraps both. Keep existing GraphQL handlers.

7. **Create SharePointTestEngine factory** - Create `createSharePointTestEngine()` that instantiates the store and all adapters, returning a unified interface.

8. **Update e2e tests to use engine** - Refactor `sharepoint-sync.e2e-spec.ts` to use the new `SharePointTestEngine` instead of individual mocks.

9. **Add default seed data** - Create sensible default seed state that mirrors current mock defaults (one drive, one file, one user, one scope).
