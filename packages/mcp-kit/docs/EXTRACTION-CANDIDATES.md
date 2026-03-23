# EXTRACTION-CANDIDATES.md

Analysis of all 65 MCP Kit tickets to identify cross-cutting candidates for extraction into `@unique-ag/mcp-kit`.

## Summary

**Total cross-cutting candidates identified: 36 tickets** (referenced by 3+ other tickets across 2+ different areas)
- **Pure TypeScript (extractable):** 10 candidates
- **Partially extractable:** 4 candidates
- **Framework-internal (cannot extract):** 22 candidates

**Recommended initial extraction: 5 core candidates** (Errors, Identity, Branded types, Session store, Auth provider interface)

---

## High-Priority Cross-Cutting Candidates

### 1. CORE-031: Error Hierarchy & Exception Handling
**Current Home:** CORE-031-exception-filter-error-hierarchy
**Referenced By:** CORE-010, CORE-013, AUTH-001, AUTH-007, CONN-003, CONN-004, CONN-005, SDK-001 (8 references)
**Cross-Area Usage:** CORE, AUTH, CONN, SDK
**NestJS Dependency:** No (pure Error classes + utility function)
**Category:** Error class + utility function

**Defines:**
- `McpBaseError` (abstract base error class)
- `DefectError` (invariant violation error)
- `invariant(condition, message)` (utility function with TypeScript assertion)
- Concrete error classes:
  - `McpAuthenticationError` (MCP_AUTHENTICATION_FAILED)
  - `McpAuthorizationError` (MCP_AUTHORIZATION_FAILED)
  - `McpValidationError` (MCP_VALIDATION_FAILED)
  - `McpToolError` (MCP_TOOL_ERROR)
  - `McpProtocolError` (MCP_PROTOCOL_ERROR)
  - `UpstreamConnectionRequiredError` (with reconnectUrl field)
  - `UpstreamConnectionLostError` (upstreamName field)
- `handleMcpToolError()` (error handler utility)
- `McpHttpExceptionFilter` (NestJS filter - stays in framework)

**Extraction Status:** ✅ **YES** - Pure TypeScript error hierarchy with zero NestJS dependencies. Foundational to entire framework.

---

### 2. CORE-006: McpIdentity Interface
**Current Home:** CORE-006-mcp-identity
**Referenced By:** AUTH-001, AUTH-002, AUTH-005, AUTH-007, CORE-005, CORE-007, CORE-009, CORE-011, CORE-012, TRANS-001 (11 references)
**Cross-Area Usage:** AUTH, CORE, TRANS
**NestJS Dependency:** No (pure interface + helper)
**Category:** Type/Interface

**Defines:**
- `McpIdentity` interface with fields:
  - `userId: string`
  - `profileId: string`
  - `clientId: string`
  - `email: string | undefined`
  - `displayName: string | undefined`
  - `scopes: string[]`
  - `resource: string`
  - `raw: unknown` (original token data)
- `getMcpIdentity(context: ExecutionContext): McpIdentity | null` helper

**Extraction Status:** ✅ **YES** - Cross-cutting identity abstraction used by every auth mode, all handlers, and session management.

---

### 3. AUTH-001: Auth Provider Interface & Branded Types
**Current Home:** AUTH-001-mcp-auth-module-restructure
**Referenced By:** AUTH-002-009, CONN-002, CORE-001, CORE-012, CORE-015, CORE-031 (14 references)
**Cross-Area Usage:** AUTH, CONN, CORE
**NestJS Dependency:** Yes for module, **NO for interfaces**
**Category:** Interface + Type/Brand

**Defines (extractable parts):**
- `McpAuthProvider` interface (validate method contract)
- `TokenValidationResult` (discriminated union on `source: 'oauth' | 'jwt'`)
- Branded types:
  - `BearerToken = z.string().min(1).brand('BearerToken')`
  - `HmacSecret = z.string().min(32).brand('HmacSecret')`
  - `Scope = z.string().min(1).brand('Scope')`

**Extraction Status:** ⭐ **PARTIAL** - Extract pure TS interfaces and brands; keep NestJS module in framework.

---

### 4. SESS-001: Session Store Interface & Default Implementation
**Current Home:** SESS-001-session-store-interface
**Referenced By:** CORE-013, SESS-002, SESS-003, SESS-004, SDK-006, SDK-007, TRANS-001 (8 references)
**Cross-Area Usage:** CORE, SDK, SESS, TRANS
**NestJS Dependency:** No (pure interface + class)
**Category:** Interface + service class

**Defines:**
- `McpSessionRecord` interface (sessionId, transportType, userId, profileId, clientId, scopes, resource, protocolVersion, clientInfo, serverName, createdAt, lastActivityAt, expiresAt)
- `McpSessionStore` interface (save, get, delete, findByUserId, findByClientId, deleteByUserId, touch, deleteExpired)
- `InMemorySessionStore` implementation (Map-based with TTL awareness)
- `MCP_SESSION_STORE` injection token

**Extraction Status:** ✅ **YES** - Zero-config default session store implementation. Pure TypeScript. Used by all transport layers.

---

### 5. CONN-003: Upstream Provider Registry & OAuth Utilities
**Current Home:** CONN-003-upstream-provider-registry
**Referenced By:** CONN-001, CONN-002, CONN-004, CONN-005, AUTH-008, CORE-031 (7 references)
**Cross-Area Usage:** AUTH, CONN, CORE
**NestJS Dependency:** No for config/utilities, **YES for UpstreamProviderRegistry service**
**Category:** Interface + service + utility

**Defines (extractable parts):**
- `UpstreamProviderConfig` interface
- `OAuthTokenResponse` interface
- OAuth utility functions (pure TS):
  - `buildAuthorizationUrl(providerId, redirectUri, state, scopes?, codeVerifier?): string`
  - `exchangeCode(providerId, code, redirectUri, codeVerifier?): Promise<OAuthTokenResponse>`
  - `refreshToken(providerId, refreshToken): Promise<OAuthTokenResponse>`
- PKCE support utilities

**Extraction Status:** ⭐ **PARTIAL** - Extract pure TS types and utility functions; keep registry service in framework.

---

### 6. CORE-007: McpContext Interface & Related Types
**Current Home:** CORE-007-mcp-context
**Referenced By:** CORE-006, CORE-010, CORE-013, CORE-024, SDK-001, SDK-002, SDK-006, SDK-007 (8 references)
**Cross-Area Usage:** CORE, SDK
**NestJS Dependency:** No (pure types)
**Category:** Type/Interface

**Defines (type-only):**
- `ResourceRef` interface (uri, name, description?, mimeType?)
- `PromptRef` interface (name, description?, arguments?)
- `PromptResult` interface (description?, messages)
- `McpContext` interface signatures (for extraction; implementation stays in framework)

**Extraction Status:** ✅ **YES** - Core types needed by all SDK consumers. Interfaces extracted; implementations stay in framework.

---

### 7. SESS-004: Session Registry Service
**Current Home:** SESS-004-session-registry-service
**Referenced By:** AUTH-001, SDK-004, SDK-005, SDK-006, SDK-007, CORE-017, CORE-029, TRANS-001, TRANS-002 (12 references)
**Cross-Area Usage:** AUTH, CORE, SDK, SESS, TRANS
**NestJS Dependency:** Yes (@Injectable)
**Category:** NestJS Service

**Status:** ⛔ **CANNOT EXTRACT** - Heavily NestJS-dependent, SESSION-scoped, tightly coupled to DI container.

---

### 8. CORE-010: Pipeline Runner & Execution Context
**Current Home:** CORE-010-pipeline-runner
**Referenced By:** AUTH-007, CONN-005, CORE-001, CORE-005, CORE-007, CORE-009, CORE-011-013, CORE-031 (14 references)
**Cross-Area Usage:** AUTH, CONN, CORE
**NestJS Dependency:** Yes (context machinery)
**Category:** Framework pipeline

**Status:** ⛔ **CANNOT EXTRACT** - Core NestJS context machinery; cannot decouple from execution context host.

---

### 9. CORE-005: Handler Registry
**Current Home:** CORE-005-handler-registry
**Referenced By:** 21 internal references across CORE
**Cross-Area Usage:** CORE
**NestJS Dependency:** Yes
**Category:** Service + registry

**Status:** ⛔ **CANNOT EXTRACT** - Central registry tightly coupled to framework lifecycle.

---

### 10. CORE-013: MCP Handlers (Tools, Resources, Prompts)
**Current Home:** CORE-013-mcp-handlers
**Referenced By:** 27 references across all areas
**Cross-Area Usage:** CORE, AUTH, SDK, SESS
**NestJS Dependency:** Yes
**Category:** Framework handlers

**Status:** ⛔ **CANNOT EXTRACT** - Core handler execution layer; NestJS-dependent.

---

## Additional Cross-Cutting Candidates (6-36)

### Candidates 11-20: Decorator Layer (Cannot Extract)
- **CORE-001** (@Tool decorator)
- **CORE-002** (@Resource decorator)
- **CORE-003** (@Prompt decorator)
- **CORE-004** (@Ctx parameter decorator)

Status: ⛔ All require NestJS metadata system; cannot extract.

### Candidates 21-25: SDK Wrapper Layer (Partially Extractable)
- **SDK-001** (ctx.elicit)
- **SDK-002** (ctx.sample)
- **SDK-003** (ctx.tasks)
- **SDK-004** (ctx.subscribeResource)
- **SDK-005** (ctx.listChanges)

Status: ⭐ Core types/schemas extractable; wrapper implementations stay in framework.

### Candidates 26-30: Connection Management (Partially Extractable)
- **CONN-001** (UpstreamConnectionStore) - interfaces extractable
- **CONN-002** (Required connections pre-auth)
- **CONN-004** (@RequiresConnection decorator)
- **CONN-005** (Reconnection elicitation)

Status: ⭐ Interfaces → extract; decorators & services → stay.

### Candidates 31-36: Transport & Testing (Cannot Extract)
- **TRANS-001** (Streamable HTTP transport)
- **TRANS-002** (SSE transport)
- **TRANS-003** (STDIO transport)
- **TEST-001** (Testing module)
- **TEST-002** (Test client)

Status: ⛔ NestJS-specific transport adapters; cannot extract.

---

## Extraction Strategy: Phased Approach

### Phase 1: Errors & Core Types Foundation
**Depends on:** INFRA-001 (package scaffold)
**Creates:** `@unique-ag/mcp-kit` v0.1.0

Extract from:
1. **CORE-031** → `src/errors/`
   - Error classes (abstract + concrete)
   - `invariant()` utility with TypeScript assertion
   - `handleMcpToolError()` error handler

2. **CORE-006** → `src/types/mcp-identity.ts`
   - `McpIdentity` interface
   - `getMcpIdentity()` helper

3. **AUTH-001** (partial) → `src/types/brands.ts`
   - `BearerToken`, `HmacSecret`, `Scope` branded types

4. **INFRA-001** → `src/types/core-brands.ts`
   - Consolidate `UserId`, `ClientId`, `ProviderId` branded types

**Package structure:**
```
@unique-ag/mcp-kit/
├── src/
│   ├── errors/
│   │   ├── defect.ts (DefectError, invariant)
│   │   ├── base.ts (McpBaseError, McpErrorMetadata)
│   │   ├── failures.ts (all concrete error classes)
│   │   ├── handler.ts (handleMcpToolError)
│   │   └── index.ts
│   ├── types/
│   │   ├── mcp-identity.ts
│   │   ├── brands.ts
│   │   └── index.ts
│   └── index.ts (barrel export)
├── package.json
└── tsconfig.json
```

**Zero external dependencies** (only TypeScript + Zod for brands)

---

### Phase 2: Session & Connection Contracts
**Depends on:** Phase 1 (`@unique-ag/mcp-kit`)
**Updates:** `@unique-ag/mcp-kit` v0.2.0

Extract from:
5. **SESS-001** → `src/session/`
   - `McpSessionStore` interface
   - `McpSessionRecord` interface
   - `InMemorySessionStore` implementation
   - `MCP_SESSION_STORE` injection token

6. **CONN-003** (partial) → `src/connection/`
   - `UpstreamProviderConfig` interface
   - `OAuthTokenResponse` interface
   - OAuth utilities (buildAuthorizationUrl, exchangeCode, refreshToken)

**Package additions:**
```
@unique-ag/mcp-kit/
├── src/
│   ├── session/
│   │   ├── interfaces/
│   │   │   ├── session-store.ts
│   │   │   └── session-record.ts
│   │   ├── stores/
│   │   │   └── in-memory-session.store.ts
│   │   ├── constants.ts (MCP_SESSION_STORE token)
│   │   └── index.ts
│   ├── connection/
│   │   ├── interfaces/
│   │   │   ├── provider-config.ts
│   │   │   └── oauth-token-response.ts
│   │   ├── utils/
│   │   │   └── oauth-utilities.ts
│   │   └── index.ts
```

**New dependencies:** None (pure TS interfaces + Zod)

---

### Phase 3: Core SDK Types
**Depends on:** Phase 1 + 2
**Updates:** `@unique-ag/mcp-kit` v0.3.0

Extract from:
7. **CORE-007** (partial) → `src/context/`
   - `ResourceRef`, `PromptRef`, `PromptResult` interfaces
   - Context-related type definitions (not implementations)

8. **SDK-001-007** (partial) → `src/sdk/`
   - Option schemas (for sampling, elicitation, tasks)
   - Response type definitions
   - NOT implementations (those stay in framework)

**Package additions:**
```
@unique-ag/mcp-kit/
├── src/
│   ├── context/
│   │   ├── resource-ref.ts
│   │   ├── prompt-ref.ts
│   │   └── index.ts
│   ├── sdk/
│   │   ├── sampling-options.ts
│   │   ├── elicitation-options.ts
│   │   ├── tasks-options.ts
│   │   └── index.ts
```

**New dependencies:** None

---

### Phase 4: Framework Implementation Layer
**Stays in:** `@unique-ag/nestjs-mcp`

Cannot extract:
- CORE-005 (Handler Registry)
- CORE-010 (Pipeline Runner)
- CORE-013 (MCP Handlers)
- CORE-001-004 (Decorators)
- AUTH-001 (module + services)
- All SESS/TRANS/TEST services

Framework will import types from `@unique-ag/mcp-kit` and implement handlers in-process.

---

## Extraction Candidates Reference Table

| # | Component | Ticket | Home | Refs | Areas | Extract | Reason |
|---|-----------|--------|------|------|-------|---------|--------|
| 1 | Error Hierarchy | CORE-031 | CORE | 8 | CORE,AUTH,CONN,SDK | ✅ YES | Pure TS, foundational |
| 2 | McpIdentity | CORE-006 | CORE | 11 | AUTH,CORE,TRANS | ✅ YES | Cross-cutting identity |
| 3 | TokenValidationResult | AUTH-001 | AUTH | 14 | AUTH,CONN,CORE | ✅ YES | Auth foundation |
| 4 | Branded Types (Auth) | AUTH-001 | AUTH | 14 | AUTH,CONN,CORE | ✅ YES | Pure Zod brands |
| 5 | Session Store | SESS-001 | SESS | 8 | CORE,SDK,SESS,TRANS | ✅ YES | Zero-config default |
| 6 | Provider Registry | CONN-003 | CONN | 7 | AUTH,CONN,CORE | ⭐ PART | Types yes, service no |
| 7 | Resource/Prompt Types | CORE-007 | CORE | 8 | CORE,SDK | ✅ YES | SDK types |
| 8 | Auth Provider Interface | AUTH-001 | AUTH | 14 | AUTH,CONN,CORE | ✅ YES | Plugin contract |
| 9 | OAuth Utilities | CONN-003 | CONN | 7 | AUTH,CONN,CORE | ✅ YES | Pure functions |
| 10 | Core Branded Types | INFRA-001 | INFRA | 16 | AUTH,CORE | ✅ YES | UserId, ClientId |
| 11-20 | Decorators | CORE-001-004 | CORE | 6+ | CORE | ⛔ NO | NestJS metadata |
| 21-25 | SDK Wrappers | SDK-001-007 | SDK | 4+ | CORE,SDK | ⭐ PART | Types yes, impl no |
| 26-30 | Connection Services | CONN-001,004,005 | CONN | 5+ | CONN,CORE | ⭐ PART | Interfaces yes, svcs no |
| 31-36 | Transports/Testing | TRANS-001-003, TEST | TRANS,TEST | 6+ | TEST,TRANS | ⛔ NO | NestJS adapters |

---

## Implementation Checklist

### Phase 1 Deliverables
- [ ] Create `packages/mcp-kit/` directory
- [ ] Set up `package.json`, `tsconfig.json`, `src/` structure
- [ ] Extract CORE-031 error classes
- [ ] Extract CORE-006 McpIdentity
- [ ] Extract AUTH-001 auth brands
- [ ] Extract INFRA-001 core brands
- [ ] Create barrel exports
- [ ] Update `@unique-ag/nestjs-mcp` to import from `@unique-ag/mcp-kit`
- [ ] Run tests to verify no breakage

### Phase 2 Deliverables
- [ ] Extract SESS-001 session store interfaces + InMemorySessionStore
- [ ] Extract CONN-003 provider config + OAuth utilities
- [ ] Update transport implementations to use extracted types
- [ ] Update session layer to use extracted store

### Phase 3 Deliverables
- [ ] Extract CORE-007 context types
- [ ] Extract SDK-001-007 type schemas
- [ ] Update SDK wrappers to import from kit

---

## Notes

- All extracted code is **pure TypeScript** with minimal dependencies (only Zod for branded types)
- Framework implementation stays in `@unique-ag/nestjs-mcp` and imports types from `@unique-ag/mcp-kit`
- Clear separation: **types/contracts → `@unique-ag/mcp-kit`** | **services/handlers → `@unique-ag/nestjs-mcp`**
- Per conventions.md, all error classes and types follow established patterns (branded types with Zod, undefined-only for optional fields, null only for explicit architectural contracts)

