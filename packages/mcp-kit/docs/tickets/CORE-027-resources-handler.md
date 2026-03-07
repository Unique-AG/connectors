# CORE-027: McpResourcesHandler

## Summary
Implement `McpResourcesHandler`, the handler service that registers SDK request handlers for resource-related MCP protocol operations (ListResources, ListResourceTemplates, ReadResource). The handler retrieves the correct method from the registry, runs it through the pipeline, injects `McpContext` at the `@Ctx()` position, and returns the properly formatted MCP response. It also handles resource template URI matching, tag-based filtering at list time, and subscribe/unsubscribe routing.

> **Note:** This ticket follows the same structural patterns as CORE-013 (McpToolsHandler). Read CORE-013 for common handler infrastructure details.

## Background / Context
The resources handler service registers SDK request handlers for resource-related MCP protocol operations. It delegates to `McpPipelineRunner` for the full NestJS guard/interceptor/pipe pipeline and constructs `McpContext` for injection via `@Ctx()`.

The handler is orchestrated by `McpExecutorService` which registers it on the `McpServer` instance. It is REQUEST-scoped (tied to the HTTP request that established the MCP connection).

Resources in the unified `@Resource()` decorator model can be either static (fixed URI) or templated (URI pattern with `{param}` placeholders). The handler must distinguish between both types at list time and route `ReadResource` requests to the correct handler by matching against static URIs first, then template patterns.

## Acceptance Criteria

### List-time authorization filtering (FastMCP parity)
- [ ] `McpResourcesHandler.listResources()` evaluates per-resource guards before including a resource in the response — guarded resources that the current identity would fail are excluded
- [ ] `McpResourcesHandler.listResourceTemplates()` evaluates per-resource-template guards before including a template in the response
- [ ] A component that a guard would block MUST NOT appear in list responses
- [ ] Guard that throws during list evaluation → component excluded from list, NO error propagated to client
- [ ] Guard that returns false during list evaluation → component excluded from list
- [ ] Components without guards always appear in list responses
- [ ] Uses `McpPipelineRunner.canList(handlerMeta, identity)` for list-time guard checks
- [ ] Tag-based filtering: `listResources()` and `listResourceTemplates()` respect tag filters from the request or session configuration, excluding resources whose tags do not match

### McpResourcesHandler
- [ ] Registers `ListResourcesRequestSchema` handler — returns all static resources that pass list-time guard evaluation, with uri, name, description, mimeType, annotations, _meta
- [ ] Registers `ListResourceTemplatesRequestSchema` handler — returns all template resources that pass list-time guard evaluation, with uriTemplate, name, description, mimeType, annotations, _meta
- [ ] Registers `ReadResourceRequestSchema` handler — finds resource by URI (static match first, then template match), runs full pipeline, returns result
- [ ] Template resources: extracts params from URI using template pattern matching, passes as input
- [ ] Static resources: invokes handler with empty input
- [ ] Unknown resource URI returns `McpError(MethodNotFound)` mentioning the URI
- [ ] Injects `McpContext` at the `@Ctx()` parameter position
- [ ] Subscribe/unsubscribe routing: delegates `SubscribeRequestSchema` and `UnsubscribeRequestSchema` to the resource subscription system (SDK-004)

## BDD Scenarios

```gherkin
Feature: MCP Resources Handler
  The resources handler registers SDK request handlers for resource operations,
  routes reads through the pipeline, matches URIs to static and template resources,
  injects context, and filters list responses based on authorization and tags.

  Background:
    Given an MCP server is running with registered resources

  Rule: Resource read routing and execution

    Scenario: Static resource read is routed to the correct handler
      Given a static resource "config://app/settings" is registered
      When a client reads resource "config://app/settings"
      Then the resource handler is invoked with empty input
      And the response contains the handler's return value

    Scenario: Resource template URI parameters are extracted
      Given a resource template with URI pattern "users://{user_id}/profile"
      When a client reads resource "users://abc-123/profile"
      Then the handler is invoked with user_id "abc-123"

    Scenario: Template with multiple parameters extracts all values
      Given a resource template with URI pattern "repos://{owner}/{repo}/readme"
      When a client reads resource "repos://acme/widgets/readme"
      Then the handler is invoked with owner "acme" and repo "widgets"

    Scenario: Static URI takes precedence over template match
      Given a static resource "users://admin/profile" is registered
      And a resource template with URI pattern "users://{user_id}/profile" is registered
      When a client reads resource "users://admin/profile"
      Then the static resource handler is invoked, not the template handler

    Scenario: Unknown resource URI returns an error
      Given no resource matches URI "unknown://resource"
      When a client reads resource "unknown://resource"
      Then the client receives a "method not found" error mentioning "unknown://resource"

    Scenario: MCP context is injected into the resource handler
      Given a resource "config://app/settings" whose handler accepts an MCP context parameter
      When a client reads resource "config://app/settings"
      Then the handler receives a context with operation type "resource" and operation name "config://app/settings"

    Scenario: Pipeline components are applied to resource reads
      Given a global logging interceptor and a per-resource admin guard are configured
      When a client reads a guarded resource
      Then the guard evaluates access before the handler runs
      And the interceptor wraps the handler execution

  Rule: List responses

    Scenario: All registered static resources appear in the resource list
      Given 3 static resources are registered with URIs, names, and descriptions
      When a client requests the resource list
      Then the response contains all 3 resources with their URIs, names, and descriptions

    Scenario: All registered resource templates appear in the template list
      Given 2 resource templates are registered with URI patterns and descriptions
      When a client requests the resource template list
      Then the response contains all 2 templates with their URI patterns and descriptions

  Rule: List-time authorization filtering

    Scenario: Guarded resource is hidden from unauthorized callers
      Given a resource "secret://config" that requires the "admin" role
      And a resource "public://info" with no access restrictions
      And the current session does not have the "admin" role
      When a client requests the resource list
      Then "public://info" appears in the response
      And "secret://config" does not appear in the response

    Scenario: Guarded resource is visible to authorized callers
      Given a resource "secret://config" that requires the "admin" role
      And the current session has the "admin" role
      When a client requests the resource list
      Then "secret://config" appears in the response

    Scenario: Guarded resource template is hidden from unauthorized callers
      Given a resource template "admin://{id}/details" that requires the "admin" role
      And the current session does not have the "admin" role
      When a client requests the resource template list
      Then "admin://{id}/details" does not appear in the response

    Scenario: Guard error during list evaluation silently excludes the resource
      Given a resource "flaky://resource" whose guard throws an unexpected error during evaluation
      And other resources are registered normally
      When a client requests the resource list
      Then "flaky://resource" is excluded from the response
      And no error is returned to the client
      And other resources appear normally

    Scenario: Unguarded resources are always visible regardless of caller identity
      Given a resource "public://data" with no access restrictions
      When any caller requests the resource list
      Then "public://data" appears in the response

  Rule: Tag-based filtering at list time

    Scenario: Resources are filtered by tag when tag filter is active
      Given a resource "email://inbox" tagged with "email"
      And a resource "calendar://events" tagged with "calendar"
      And the session has an active tag filter for "email"
      When a client requests the resource list
      Then "email://inbox" appears in the response
      And "calendar://events" does not appear in the response

    Scenario: Resources with no tags are excluded when tag filter is active
      Given a resource "misc://data" with no tags
      And the session has an active tag filter for "email"
      When a client requests the resource list
      Then "misc://data" does not appear in the response

  Rule: Subscribe and unsubscribe routing

    Scenario: Subscribe request is delegated to the subscription system
      Given a resource "data://live-feed" with subscribe support
      When a client sends a subscribe request for "data://live-feed"
      Then the request is delegated to the resource subscription system (SDK-004)

    Scenario: Unsubscribe request is delegated to the subscription system
      Given a client is subscribed to "data://live-feed"
      When the client sends an unsubscribe request for "data://live-feed"
      Then the request is delegated to the resource subscription system (SDK-004)
```

## Dependencies
- Depends on: CORE-002 — @Resource() decorator metadata
- Depends on: CORE-005 — registry for looking up handlers
- Depends on: CORE-007 — McpContext construction
- Depends on: CORE-008 — output serialization
- Depends on: CORE-009 — McpExecutionContextHost needed to build list-time guard evaluation context
- Depends on: CORE-010 — pipeline runner for guard/interceptor/pipe execution; `canList()` method
- Depends on: CORE-012 — module wiring provides McpServer and config
- Depends on: CORE-013 — common handler infrastructure patterns
- Blocks: SDK-004 — resource subscriptions extend resource handler behavior
- Blocks: CORE-023 — static resource classes registered as resources

## Technical Notes
- The handler registers on `mcpServer.server.setRequestHandler()` (low-level SDK Server, not McpServer high-level API) to maintain full control over the request/response flow
- Resource template URI matching uses the URI Template spec (RFC 6570 Level 1) for `{param}` extraction. A simple regex-based matcher is sufficient for Level 1 templates.
- Match priority for `ReadResource`: exact static URI match first, then iterate template patterns. First template match wins (registration order).
- Resource handlers must check both static and template resources when matching URIs (unified @Resource decorator means both are in the same registry)
- Subscribe/unsubscribe handlers are no-ops if SDK-004 is not implemented yet — they return success without side effects, logging a warning
- `McpContext` for resource operations uses `operationType: 'resource'` (static) or `operationType: 'resource-template'` (template)
- File location: `packages/nestjs-mcp/src/services/handlers/mcp-resources.handler.ts`
- SDK APIs used:
  - `mcpServer.server.setRequestHandler(ListResourcesRequestSchema, ...)`
  - `mcpServer.server.setRequestHandler(ListResourceTemplatesRequestSchema, ...)`
  - `mcpServer.server.setRequestHandler(ReadResourceRequestSchema, ...)`
  - `mcpServer.server.setRequestHandler(SubscribeRequestSchema, ...)` (delegates to SDK-004)
  - `mcpServer.server.setRequestHandler(UnsubscribeRequestSchema, ...)` (delegates to SDK-004)
