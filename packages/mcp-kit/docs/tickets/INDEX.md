# @unique-ag/nestjs-mcp — Implementation Ticket Index

> **Total tickets:** 67
> **Design artifact:** `.claude/artifacts/mcp-nestjs-framework-final.md`
> **Testing approach:** BDD (Given/When/Then) — all tickets include full scenario coverage

---

## Dependency Graph

```
INFRA-001  (Monorepo package scaffold)
├── CORE-031  (McpExceptionFilter & Error Hierarchy)  ─► CORE-010, CORE-013, CORE-027, CORE-028, AUTH-001, AUTH-007, CONN-003, CONN-004, SDK-001
│
├── CORE-001  (@Tool decorator)           ─► CORE-018, CORE-019
├── CORE-002  (@Resource decorator)       ─► CORE-018, CORE-023
├── CORE-003  (@Prompt decorator)         ─► CORE-018
├── CORE-004  (@Ctx parameter decorator)
├── CORE-008  (Output auto-serialization)
│
└─► CORE-005  (Handler registry)  ← CORE-001 + CORE-002 + CORE-003 + CORE-004
    ├── CORE-009  (ExecutionContextHost)
    │   ├── CORE-010  (Pipeline runner)  ← + CORE-008
    │   │   ├── CORE-007  (McpContext)   ← + CORE-006
    │   │   │   ├── SDK-001  (ctx.elicit)
    │   │   │   ├── SDK-002  (ctx.sample)
    │   │   │   ├── SDK-006  (ctx.session state)       ← + SESS-001, SESS-004
    │   │   │   └── SDK-007  (ctx.session visibility)  ← + SESS-001, CORE-013, CORE-015
    │   │   └── CORE-011  (Built-in pipeline components) ← + CORE-006, CORE-009
    │   └── CORE-006  (McpIdentity + resolver)  ← + CORE-005
    │
    └── CORE-012  (McpModule config)  ← CORE-010 + CORE-011
        ├── CORE-013  (McpToolsHandler)  ← + CORE-007 + CORE-008
        │   ├── CORE-027  (McpResourcesHandler) ← + CORE-002
        │   │   ├── SDK-004  (Resource subscriptions) ← + SESS-004
        │   │   └── CORE-023  (Static resource classes)
        │   ├── CORE-028  (McpPromptsHandler) ← + CORE-003
        │   ├── SESS-001  (Session store interface)
        │   │   ├── SESS-002  (Redis session store)
        │   │   ├── SESS-003  (Drizzle session store)
        │   │   └── SESS-004  (Session registry + service)
        │   │       ├── SESS-005  (Session registration tracking)
        │   │       │   ├── SESS-006  (Session resumption)  ← + SESS-004
        │   │       │   │   └── TRANS-001  (Streamable HTTP)
        │   │       │   └── TRANS-002  (SSE transport)
        │   │       ├── SDK-004  (Resource subscriptions) ← + CORE-002, CORE-027
        │   │       └── SDK-005  (List change notifications) ← + CORE-013
        │   │                                               ─► CORE-020
        │   ├── SDK-003  (Tasks API) ← + CORE-001
        │   ├── CORE-017  (Proxy module) ← + CORE-001, CORE-005, SESS-004
        │   │   ├── CORE-029  (Proxy feature forwarding) ← + SESS-004, SDK-001, SDK-002
        │   │   └── CORE-030  (Proxy McpModule integration) ← + CORE-012, CORE-013
        │   ├── CORE-024  (getMcpContext utility)
        │   ├── CORE-025  (Schema dereferencing)
        │   └── CORE-026  (Transforms)
        │
        ├── CORE-021  (Custom HTTP routes)
        ├── CORE-022  (Server lifespan hooks)
        │
        ├── AUTH-001  (Auth module restructure) ← + CORE-006, SESS-004
        │   ├── AUTH-002  (Token userData denorm) ← + CORE-006
        │   ├── AUTH-003  (Drizzle OAuth store)
        │   │   └── AUTH-004  (Prisma OAuth store) ← + AUTH-001
        │   ├── AUTH-005  (JWT token verifier) ← + CORE-006
        │   │   ├── AUTH-006  (Multi-auth)
        │   │   └── AUTH-009  (RemoteAuthProvider + AuthKit)
        │   ├── AUTH-007  (Component-level auth) ← + CORE-001/002/003, CORE-006, CORE-013
        │   ├── AUTH-008  (OAuthProxy + GitHub) ← + TRANS-001
        │   └── CORE-015  (Tag-based filtering) ← + CORE-001/002/003, CORE-005, CORE-013, SDK-005
        │
        ├── TRANS-003  (STDIO transport)
        ├── CORE-016  (Server composition) ← + CORE-001, CORE-005
        └── TEST-001  (Testing module)  ← + TEST-002, TRANS-001/002/003

    CORE-014  (Argument completions) ← CORE-001, CORE-005
    CORE-018  (Decorator metadata)   ← CORE-001, CORE-002, CORE-003, CORE-005
    CORE-019  (Injectable parameters) ← CORE-001, CORE-005

    TEST-002  (Test client — standalone)

    CONN-001  (Upstream connection store)     ─► CONN-002, CONN-003, CONN-004, CONN-005
    CONN-002  (Required connections + pre-auth gate) ← CONN-001, CONN-003, AUTH-001/002
    CONN-003  (Provider registry + OAuth callback) ← CONN-001 ─► CONN-002, CONN-004, CONN-005
    CONN-004  (@RequiresConnection + McpConnectionGuard) ← CONN-001, CONN-002, CONN-003 ─► CONN-005
    CONN-005  (Runtime reconnection via elicitation) ← CONN-001, CONN-003, CONN-004, CORE-010, SDK-001
```

**Critical path:**
`INFRA-001 → CORE-031 (error foundation) → CORE-001..004 → CORE-005 → CORE-009 → CORE-010 → CORE-012 → CORE-013 → CORE-027/028 → SESS-001 → SESS-004 → SESS-005 → SESS-006 → TRANS-001`

---

## Suggested Sprint Sequence

### Sprint 1 — Foundation
| Ticket | Title |
|--------|-------|
| INFRA-001 | Monorepo package scaffold |
| INFRA-002 | Configure subpath exports (`./errors`, `./types`, `./brands`, `./session`, `./auth`, `./connection`) |
| INFRA-003 | Add lint rule: no cross-subpath imports, no `@nestjs/*` in leaf subpath modules |
| CORE-031 | McpExceptionFilter & Error Hierarchy (DefectError, McpBaseError, invariant, handleMcpToolError, McpHttpExceptionFilter) |
| CORE-001 | @Tool() decorator |
| CORE-002 | @Resource() decorator (unified) |
| CORE-003 | @Prompt() decorator |
| CORE-004 | @Ctx() parameter decorator |
| CORE-005 | MCP handler registry |
| CORE-006 | McpIdentity interface + McpIdentityResolver |
| CORE-008 | Output auto-serialization (McpContent) |
| CORE-018 | Decorator metadata enhancements (icons, meta, version, title) |
| CORE-019 | Injectable / excluded parameters (@Inject DI exclusion) |

### Sprint 2 — Pipeline + Module
| Ticket | Title |
|--------|-------|
| CORE-009 | McpExecutionContextHost + switchToMcp() |
| CORE-010 | McpPipelineRunner (ExternalContextCreator integration) |
| CORE-007 | McpContext class |
| CORE-011 | Built-in pipeline components |
| CORE-012 | McpModule configuration |
| CORE-013 | McpToolsHandler |
| CORE-027 | McpResourcesHandler |
| CORE-028 | McpPromptsHandler |
| CORE-021 | Custom HTTP routes alongside MCP endpoint |
| CORE-022 | Server lifespan / startup-teardown hooks |
| CORE-024 | getMcpContext() — context access from nested services |
| CORE-025 | Schema dereferencing (derefSchemas option) |
| CORE-026 | Transforms — server-wide component presentation modifiers |

### Sprint 3 — Sessions + Transports + Testing
| Ticket | Title |
|--------|-------|
| SESS-001 | McpSessionStore interface + InMemorySessionStore |
| SESS-004 | McpSessionRegistry + McpSessionService |
| SESS-005 | Session registration + activity tracking |
| SESS-006 | Session resumption after server restart |
| TRANS-001 | Streamable HTTP transport service |
| TRANS-003 | STDIO transport service |
| CORE-023 | Static resource classes (TextResource, FileResource, HttpResource, DirectoryResource) |
| TEST-002 | McpTestClient |
| TEST-001 | McpTestingModule |

### Sprint 4 — Auth
| Ticket | Title |
|--------|-------|
| AUTH-001 | McpAuthModule restructure + sub-entrypoint |
| AUTH-002 | Token userData denormalization |
| AUTH-003 | DrizzleOAuthStore built-in implementation |
| AUTH-004 | PrismaOAuthStore built-in implementation |
| AUTH-005 | JwtTokenVerifier — Lightweight JWT Validation Mode |
| AUTH-006 | MultiAuthProvider — Multiple Auth Sources |
| AUTH-007 | Component-level auth parameter on decorators |
| AUTH-008 | OAuthProxy provider (GitHub, Google, Azure bridge) |
| AUTH-009 | RemoteAuthProvider + AuthKitProvider (DCR-compatible IdPs) |

### Sprint 5 — New SDK Features + Context Extensions
| Ticket | Title |
|--------|-------|
| SDK-001 | ctx.elicit() — structured user input |
| SDK-002 | ctx.sample() — LLM sampling |
| SDK-003 | Tasks API — @Tool({ longRunning: true }) |
| SDK-004 | Resource subscriptions — @Resource({ subscribe: true }) |
| SDK-005 | List change notifications |
| SDK-006 | ctx.get_state / ctx.set_state — Per-Session State |
| SDK-007 | ctx.enableComponents / ctx.disableComponents — Per-Session Visibility |

### Sprint 6 — Store Variants + Parity Gaps + Proxy
| Ticket | Title |
|--------|-------|
| SESS-002 | RedisSessionStore |
| SESS-003 | DrizzleSessionStore + McpSessionCleanupService |
| TRANS-002 | SSE transport service (legacy, deprecated) |
| CORE-014 | Argument completions (@Complete decorator) |
| CORE-015 | Tag-based tool filtering |
| CORE-016 | Server composition (McpModule.forFeature) |
| CORE-017 | McpProxyModule — MCP Client Bridge |
| CORE-029 | Proxy feature forwarding |
| CORE-030 | Proxy McpModule integration |

### Sprint 7 — Runtime Management
| Ticket | Title |
|--------|-------|
| CORE-020 | Dynamic component management (runtime add/remove) |

### Sprint 8 — Upstream Connections (Multi-Provider Auth)
| Ticket | Title |
|--------|-------|
| CONN-001 | Upstream connection store (data model + encryption + pluggable storage) |
| CONN-003 | Upstream provider registry + OAuth callback controller |
| CONN-002 | Required connections declaration + pre-auth gate + well-known endpoint |
| CONN-004 | @RequiresConnection decorator + McpConnectionGuard |
| CONN-005 | Runtime reconnection via MCP URL elicitation |

---

## All Tickets by Area

### INFRA — Infrastructure

| ID | Title | Depends on | Blocks |
|----|-------|------------|--------|
| INFRA-001 | Monorepo package scaffold | — | CORE-001, CORE-002, CORE-003, CORE-004, CORE-008 |
| INFRA-002 | Configure subpath exports in package.json | INFRA-001 | — |
| INFRA-003 | Add barrel export lint rule (no cross-subpath imports, no @nestjs in leaf modules) | INFRA-001 | — |

### CORE — Core Framework

| ID | Title | Depends on | Blocks |
|----|-------|------------|--------|
| CORE-001 | @Tool() decorator | INFRA-001 | CORE-005, SDK-003, CORE-014, CORE-016, CORE-018, CORE-019 |
| CORE-002 | @Resource() decorator (unified) | INFRA-001 | CORE-005, SDK-004, CORE-015, CORE-018, CORE-023 |
| CORE-003 | @Prompt() decorator | INFRA-001 | CORE-005, CORE-015, CORE-018 |
| CORE-004 | @Ctx() parameter decorator | INFRA-001 | CORE-005 |
| CORE-005 | MCP handler registry | CORE-001, CORE-002, CORE-003, CORE-004 | CORE-006, CORE-009, CORE-014, CORE-015, CORE-016, CORE-018, CORE-019, CORE-020, CORE-022, CORE-023 |
| CORE-006 | McpIdentity interface + McpIdentityResolver | CORE-005, CORE-009 | CORE-007, CORE-011, AUTH-002, AUTH-007 |
| CORE-007 | McpContext class | CORE-006, CORE-010 | CORE-013, CORE-024, SDK-001, SDK-002, SDK-006, SDK-007 |
| CORE-008 | Output auto-serialization (McpContent) | INFRA-001 | CORE-013 |
| CORE-009 | McpExecutionContextHost + switchToMcp() | CORE-005 | CORE-006, CORE-010, CORE-011 |
| CORE-010 | McpPipelineRunner | CORE-005, CORE-008, CORE-009 | CORE-007, CORE-011, CORE-012 |
| CORE-011 | Built-in pipeline components | CORE-006, CORE-009, CORE-010 | CORE-012 |
| CORE-012 | McpModule configuration | CORE-005, CORE-006, CORE-010, CORE-011 | CORE-013, CORE-020, CORE-021, CORE-022, CORE-025, CORE-026, AUTH-001, CORE-016, TEST-001, TRANS-003 |
| CORE-013 | McpToolsHandler | CORE-004, CORE-005, CORE-007, CORE-008, CORE-009, CORE-010, CORE-012 | CORE-027, CORE-028, SESS-001, SDK-003, SDK-005, CORE-017, CORE-024, CORE-025, CORE-026, AUTH-007 |
| CORE-014 | Argument completions (@Complete decorator) | CORE-001, CORE-005 | — |
| CORE-015 | Tag-based tool filtering | CORE-001, CORE-002, CORE-003, CORE-005, AUTH-001, CORE-013, SDK-005 | SDK-007 |
| CORE-016 | Server composition (McpModule.forFeature) | CORE-001, CORE-005, CORE-012 | — |
| CORE-017 | McpProxyModule — MCP Client Bridge | CORE-001, CORE-005, CORE-013, SESS-004 | CORE-029, CORE-030 |
| CORE-018 | Decorator metadata enhancements (icons, meta, version, title) | CORE-001, CORE-002, CORE-003, CORE-005, CORE-012 | — |
| CORE-019 | Injectable / excluded parameters (@Inject DI exclusion) | CORE-001, CORE-005 | — |
| CORE-020 | Dynamic component management (runtime add/remove) | CORE-005, CORE-012, SDK-005 | — |
| CORE-021 | Custom HTTP routes alongside MCP endpoint | CORE-012 | — |
| CORE-022 | Server lifespan / startup-teardown hooks | CORE-005, CORE-012 | — |
| CORE-023 | Static resource classes (TextResource, FileResource, HttpResource, DirectoryResource) | CORE-002, CORE-005, CORE-027 | — |
| CORE-024 | getMcpContext() — context access from nested services | CORE-007, CORE-013 | AUTH-007 |
| CORE-025 | Schema dereferencing (derefSchemas option) | CORE-012, CORE-013 | — |
| CORE-026 | Transforms — server-wide component presentation modifiers | CORE-012, CORE-013 | — |
| CORE-027 | McpResourcesHandler | CORE-002, CORE-005, CORE-007, CORE-008, CORE-009, CORE-010, CORE-012, CORE-013 | SDK-004, CORE-023 |
| CORE-028 | McpPromptsHandler | CORE-003, CORE-005, CORE-007, CORE-008, CORE-009, CORE-010, CORE-012, CORE-013 | — |
| CORE-029 | Proxy feature forwarding | CORE-017, SESS-004, SDK-001, SDK-002 | — |
| CORE-030 | Proxy McpModule integration | CORE-017, CORE-012, CORE-013 | — |
| CORE-031 | McpExceptionFilter & Error Hierarchy | INFRA-001 | CORE-010, CORE-013, CORE-027, CORE-028, AUTH-001, AUTH-007, CONN-003, CONN-004, SDK-001 |

### SESS — Sessions

| ID | Title | Depends on | Blocks |
|----|-------|------------|--------|
| SESS-001 | McpSessionStore interface + InMemorySessionStore | CORE-013 | SESS-002, SESS-003, SESS-004, SDK-006, SDK-007 |
| SESS-002 | RedisSessionStore | SESS-001 | — |
| SESS-003 | DrizzleSessionStore + McpSessionCleanupService | SESS-001 | — |
| SESS-004 | McpSessionRegistry + McpSessionService | SESS-001 | SESS-005, SESS-006, SDK-004, SDK-005, AUTH-001, SDK-006, CORE-017 |
| SESS-005 | Session registration + activity tracking | SESS-004 | SESS-006, TRANS-001, TRANS-002 |
| SESS-006 | Session resumption after server restart | SESS-004, SESS-005 | TRANS-001 |

### TRANS — Transports

| ID | Title | Depends on | Blocks |
|----|-------|------------|--------|
| TRANS-001 | Streamable HTTP transport service | SESS-004, SESS-005, SESS-006 | TEST-001, AUTH-008 |
| TRANS-002 | SSE transport service (legacy, deprecated) | SESS-004, SESS-005 | TEST-001 |
| TRANS-003 | STDIO transport service | CORE-012 | TEST-001 |

### AUTH — Authentication

| ID | Title | Depends on | Blocks |
|----|-------|------------|--------|
| AUTH-001 | McpAuthModule restructure + sub-entrypoint | CORE-012, CORE-006, SESS-004 | AUTH-002, AUTH-003, AUTH-004, AUTH-005, AUTH-006, AUTH-007, AUTH-008, AUTH-009 |
| AUTH-002 | Token userData denormalization | AUTH-001, CORE-006 | — |
| AUTH-003 | DrizzleOAuthStore built-in implementation | AUTH-001 | AUTH-004 |
| AUTH-004 | PrismaOAuthStore built-in implementation | AUTH-001, AUTH-003 | — |
| AUTH-005 | JwtTokenVerifier — Lightweight JWT Validation Mode | AUTH-001, CORE-006 | AUTH-006, AUTH-009 |
| AUTH-006 | MultiAuthProvider — Multiple Auth Sources | AUTH-001, AUTH-005 | — |
| AUTH-007 | Component-level auth parameter on decorators | CORE-001, CORE-002, CORE-003, CORE-006, CORE-013, CORE-024, AUTH-001 | — |
| AUTH-008 | OAuthProxy provider (GitHub, Google, Azure bridge) | AUTH-001, TRANS-001 | — |
| AUTH-009 | RemoteAuthProvider + AuthKitProvider (DCR-compatible IdPs) | AUTH-001, AUTH-005 | — |

### SDK — New SDK Feature Integrations

| ID | Title | Depends on | Blocks |
|----|-------|------------|--------|
| SDK-001 | ctx.elicit() — structured user input | CORE-007 | — |
| SDK-002 | ctx.sample() — LLM sampling | CORE-007 | — |
| SDK-003 | Tasks API — @Tool({ longRunning: true }) | CORE-001, CORE-013 | — |
| SDK-004 | Resource subscriptions — @Resource({ subscribe: true }) | CORE-002, CORE-027, SESS-004 | — |
| SDK-005 | List change notifications | SESS-004, CORE-013 | CORE-020 |
| SDK-006 | ctx.get_state / ctx.set_state — Per-Session State | CORE-007, SESS-001, SESS-004 | — |
| SDK-007 | ctx.enableComponents / ctx.disableComponents — Per-Session Visibility | CORE-007, SESS-001, CORE-013, CORE-015 | — |

### TEST — Testing

| ID | Title | Depends on | Blocks |
|----|-------|------------|--------|
| TEST-001 | McpTestingModule | TEST-002, CORE-012, TRANS-001, TRANS-002, TRANS-003 | — |
| TEST-002 | McpTestClient | — | TEST-001 |

### CONN — Upstream Connections (Multi-Provider Auth)

| ID | Title | Depends on | Blocks |
|----|-------|------------|--------|
| CONN-001 | Upstream connection store + encryption | — | CONN-002, CONN-003, CONN-004, CONN-005 |
| CONN-002 | Required connections + pre-auth gate + well-known endpoint | CONN-001, CONN-003, AUTH-001 | CONN-004 |
| CONN-003 | Upstream provider registry + OAuth callback controller | CONN-001 | CONN-002, CONN-004, CONN-005 |
| CONN-004 | @RequiresConnection decorator + McpConnectionGuard + UpstreamTokenService | CONN-001, CONN-002, CONN-003 | CONN-005 |
| CONN-005 | Runtime reconnection via MCP URL elicitation + McpReconnectionPipeline | CONN-001, CONN-003, CONN-004, CORE-010, SDK-001 | — |
