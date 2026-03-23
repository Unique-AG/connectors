# @unique-ag/mcp-kit — Completed Tickets

## Sprint 1 — Foundation

| Ticket | Title | PR |
|--------|-------|----|
| INFRA-001 | Monorepo package scaffold | (checkpoint) |
| INFRA-002 | Subpath exports (`./errors`, `./types`, `./brands`, `./session`, `./auth`, `./connection`, `./filters`) | #389 |
| INFRA-003 | `noRestrictedImports` biome lint rule (NestJS-free leaf modules) | #389 |
| CORE-031 | `McpExceptionFilter` & Error Hierarchy (`DefectError`, `McpBaseError`, 7 failure classes, `invariant()`, `handleMcpToolError()`, `McpHttpExceptionFilter`) | #389 |
| CORE-001 | `@Tool()` decorator (snake_case derivation, parameter shorthand, title→annotations, timeout, mask) | #389 |
| CORE-002 | `@Resource()` unified decorator (auto static/template detection, RFC 6570 URI template parsing) | #389 |
| CORE-003 | `@Prompt()` decorator (kebab-case derivation, parameter shorthand) | #389 |
| CORE-018 | Decorator metadata enhancements (`McpIcon`, `meta`, `icons`, `version` on all three decorators) | #389 |
| CORE-004 | `@Ctx()` parameter decorator (McpContext injection at any parameter position) | #389 |
| CORE-019 | `@McpExclude()` decorator + `param-scanner` (DI param exclusion from MCP input schema) | #389 |
| CORE-008 | Output auto-serialization (`McpContent`, `McpToolResult`, `McpResourceResult`, `formatToolResult`) | #389 |
| CORE-006 | `McpIdentity` interface + `McpIdentityResolver` REQUEST-scoped service | #389 |
| CORE-005 | `McpHandlerRegistry` (DiscoveryService scan, collision detection, URI template matching) | #389 |
