# CORE-030: Proxy McpModule Integration

## Summary
Define how `McpProxyModule` integrates with `McpModule` so that proxied components appear alongside local components in unified list responses, global guards/interceptors apply to proxied components, and the proxy can also be used standalone without `McpModule`.

## Background / Context
CORE-017 establishes the core proxy module that connects to upstream MCP servers and re-exposes their tools/resources/prompts. This ticket covers the integration layer between the proxy and the main `McpModule`, ensuring proxied components are first-class citizens in the NestJS MCP framework.

This was originally part of CORE-017 but was split out to keep the core proxy focused on transport and proxying while this ticket handles the framework integration concerns.

## Acceptance Criteria

### McpModule integration
- [ ] `McpModule.forRoot({ imports: [McpProxyModule.forRoot(...)] })` pattern is supported — the proxy module registers its components into the shared `McpRegistryService`
- [ ] Proxied tools appear in `listTools` alongside locally registered tools
- [ ] Proxied resources appear in `listResources` alongside local resources
- [ ] Proxied prompts appear in `listPrompts` alongside local prompts
- [ ] The unified list is a single flat list — no separate "proxy" section

### Global guards/interceptors apply to proxied components
- [ ] Global guards registered via `APP_GUARD` in any module apply to proxied tool calls, just as they apply to local tool calls
- [ ] Global interceptors registered via `APP_INTERCEPTOR` apply to proxied tool calls
- [ ] Global pipes registered via `APP_PIPE` apply to proxied tool call arguments
- [ ] The NestJS pipeline (guard → interceptor → pipe → handler) runs the same way for proxied components as for local ones — the proxy handler is just another handler in the pipeline

### Standalone usage
- [ ] `McpProxyModule` can be used without `McpModule` for pure proxy scenarios (no local tools)
- [ ] In standalone mode, `McpProxyModule.forRoot(...)` sets up its own minimal MCP server with only proxied components
- [ ] Standalone mode does not require `McpModule.forRoot()` to be imported

### Conflict resolution with local components
- [ ] If a proxied tool has the same name as a local tool, the `onDuplicate` setting from `McpModule.forRoot()` applies (same as CORE-016)
- [ ] In standalone mode (no McpModule), duplicate names between upstream servers follow the namespacing rules (CORE-017 auto-prefix)

## BDD Scenarios

```gherkin
Feature: Proxy McpModule Integration
  The proxy module integrates with McpModule so that proxied components
  appear alongside local components and are subject to the same pipeline.

  Rule: Proxied and local components appear in unified lists

    Scenario: Proxied and local tools appear together in the tool list
      Given an application with McpModule.forRoot() and a local tool "add_numbers"
      And McpProxyModule.forRoot() connecting to an upstream that exposes tool "get_forecast"
      When a client requests the tool list
      Then both "add_numbers" and "get_forecast" appear in a single list

    Scenario: Proxied and local resources appear together in the resource list
      Given an application with a local resource "config://app" and a proxied resource "data://weather/forecast"
      When a client requests the resource list
      Then both resources appear in a single list

  Rule: Global guards apply to proxied components

    Scenario: Global guard applies to a proxied tool call
      Given a global guard that requires scope "tools:execute"
      And a proxied tool "get_forecast" from an upstream server
      When a caller without scope "tools:execute" calls "get_forecast"
      Then the call is rejected by the guard before reaching the upstream
      When a caller with scope "tools:execute" calls "get_forecast"
      Then the call is forwarded to the upstream and succeeds

    Scenario: Global interceptor wraps proxied tool execution
      Given a global interceptor that logs execution time
      And a proxied tool "get_forecast"
      When a client calls "get_forecast"
      Then the interceptor runs around the proxied call
      And the execution time is logged

  Rule: Standalone proxy usage

    Scenario: Proxy works without McpModule for pure proxy scenarios
      Given an application that imports only McpProxyModule.forRoot() without McpModule
      And the proxy connects to an upstream server exposing tool "search"
      When a client requests the tool list
      Then "search" appears in the response
      When a client calls "search"
      Then the call is forwarded to the upstream

  Rule: Name collision between local and proxied components

    Scenario: Duplicate name between local and proxied tool uses onDuplicate setting
      Given McpModule.forRoot({ onDuplicate: 'error' }) with a local tool "search"
      And McpProxyModule connecting to an upstream that also exposes tool "search"
      When the application starts
      Then an error is thrown mentioning a name collision for "search"
```

## Dependencies
- **Depends on:** CORE-017 (McpProxyModule core) — the proxy infrastructure
- **Depends on:** CORE-012 (McpModule configuration) — `McpModule.forRoot()` and `onDuplicate` config
- **Depends on:** CORE-013 (Handlers) — handler integration for unified list responses
- **Blocks:** none

## Technical Notes
- `McpProxyModule.forRoot()` registers a `ProxyRegistryService` that implements the same `RegistryContributor` interface as `McpFeatureScanner` (CORE-016). This allows `McpRegistryService` to aggregate entries from both local and proxy sources uniformly.
- When used with `McpModule`, the proxy registers its components during `onModuleInit` — after the registry is ready but before the server starts accepting connections.
- In standalone mode, `McpProxyModule` bootstraps a minimal `McpServer` instance internally (using the SDK directly) rather than relying on `McpModule`'s server. This is a simpler code path for pure proxy use cases.
- Guard/interceptor/pipe integration works because proxied tool calls go through the same `McpPipelineRunner` (CORE-010) as local tool calls. The proxy handler is just a regular NestJS provider that delegates to the upstream client.
- File locations:
  - `packages/nestjs-mcp/src/proxy/proxy-registry.service.ts` (registry contributor)
  - `packages/nestjs-mcp/src/proxy/proxy-standalone.module.ts` (standalone mode bootstrap)
