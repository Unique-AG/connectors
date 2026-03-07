# CORE-020: Dynamic component management at runtime

## Summary
Implement runtime registration and unregistration of tools, resources, and prompts via `McpRegistryService`, with automatic list-changed notifications to all connected clients after each mutation.

## Background / Context
FastMCP supports `mcp.add_tool(bound_method)` and `mcp.local_provider.remove_tool(name)` for runtime registration. After each change, `notifications/tools/list_changed` (or the resources/prompts equivalent) is automatically sent to connected clients so they can re-fetch the updated list.

In NestJS, static registration happens at bootstrap via `McpHandlerRegistry` (CORE-005). This ticket adds a public-facing `McpRegistryService` that wraps the registry with runtime mutation support. Each mutation triggers the appropriate list-changed notification via `McpSessionService` (SDK-005). This enables use cases like: feature-flagged tools, multi-tenant tool sets, plugin systems, and admin-controlled capabilities.

## Acceptance Criteria
- [ ] `McpRegistryService` is an `@Injectable()` singleton service exported from `@unique-ag/nestjs-mcp`
- [ ] `registerTool(instance: object, methodName: string, options?: Partial<ToolOptions>): void` — registers a tool from a class instance method at runtime; validates that the method exists on the instance
- [ ] `unregisterTool(name: string): void` — removes a tool by name; no-op if tool doesn't exist
- [ ] `registerResource(instance: object, methodName: string, options?: Partial<ResourceOptions>): void` — registers a resource from a class instance method at runtime
- [ ] `unregisterResource(uri: string): void` — removes a resource by URI; no-op if resource doesn't exist
- [ ] `registerPrompt(instance: object, methodName: string, options?: Partial<PromptOptions>): void` — registers a prompt from a class instance method at runtime
- [ ] `unregisterPrompt(name: string): void` — removes a prompt by name; no-op if prompt doesn't exist
- [ ] Each register/unregister operation triggers the appropriate list-changed notification to all active sessions (`notifyToolsChanged()`, `notifyResourcesChanged()`, `notifyPromptsChanged()`)
- [ ] Runtime registration respects the `onDuplicate` setting from `McpOptions` (CORE-012) — e.g., `'error'` throws, `'replace'` overwrites, `'warn'` logs and keeps first
- [ ] `McpHandlerRegistry` updated with `addTool()`, `removeTool()`, `addResource()`, `removeResource()`, `addPrompt()`, `removePrompt()` internal methods
- [ ] Runtime-registered tools are fully functional: Zod validation, pipeline execution (guards/interceptors/pipes), `@Ctx()` injection all work identically to boot-time tools
- [ ] `options` parameter allows overriding name, description, schema, annotations, guards, etc. — if not provided, decorator metadata is read from the method (if present)
- [ ] Methods without decorator metadata require `options.name` and `options.schema` at minimum; omitting them throws a descriptive error

## BDD Scenarios

```gherkin
Feature: Dynamic component management at runtime
  Tools, resources, and prompts can be added or removed at runtime,
  with connected clients automatically notified of changes.

  Background:
    Given an MCP server is running
    And a client is connected to the server

  Rule: Tools can be registered and unregistered at runtime

    Scenario: Adding a tool at runtime makes it available to clients
      Given the server has one boot-time tool "search"
      When a server-side service registers a new tool "dynamic_tool" with a string parameter "q"
      Then a client calling listTools sees both "search" and "dynamic_tool"
      And the connected client receives a tool list changed notification

    Scenario: Removing a tool at runtime hides it from clients
      Given the server has tools "search" and "dynamic_tool"
      When a server-side service unregisters the tool "dynamic_tool"
      Then a client calling listTools sees only "search"
      And the connected client receives a tool list changed notification

    Scenario: Removing a nonexistent tool is silently ignored
      Given the server has one tool "search"
      When a server-side service unregisters the tool "nonexistent"
      Then no error occurs
      And no tool list changed notification is sent

  Rule: Resources can be registered and unregistered at runtime

    Scenario: Adding a resource at runtime makes it discoverable
      Given the server has no resources
      When a server-side service registers a resource "config://app" named "App Config"
      Then a client calling listResources sees the "App Config" resource
      And the connected client receives a resource list changed notification

    Scenario: Removing a resource at runtime hides it from clients
      Given the server has a resource "config://app"
      When a server-side service unregisters the resource "config://app"
      Then a client calling listResources sees an empty list
      And the connected client receives a resource list changed notification

  Rule: Duplicate handling respects the server configuration

    Scenario: Registering a duplicate tool in strict mode raises an error
      Given the server is configured with duplicate handling set to "error"
      And the server has a boot-time tool "search"
      When a server-side service attempts to register another tool named "search"
      Then an error is raised indicating "search" already exists
      And the original "search" tool remains unchanged

    Scenario: Registering a duplicate tool in replace mode overwrites it
      Given the server is configured with duplicate handling set to "replace"
      And the server has a boot-time tool "search" with description "old search"
      When a server-side service registers a tool "search" with description "new search"
      Then a client calling listTools sees "search" with description "new search"
      And the connected client receives a tool list changed notification

  Rule: Runtime-registered tools work identically to boot-time tools

    Scenario: A runtime-registered tool goes through the full execution pipeline
      Given the server has a global logging interceptor configured
      And a server-side service has registered a tool "dynamic_tool" with a string parameter "q"
      When a client calls "dynamic_tool" with { "q": "test" }
      Then the logging interceptor processes the call
      And input validation is applied to the arguments
      And the tool handler executes and returns a result

  Rule: Registration without metadata requires explicit options

    Scenario: Registering a plain method without name and schema fails with a clear error
      Given a server-side service has a plain method with no tool metadata
      When it attempts to register that method as a tool without providing a name or schema
      Then an error is raised indicating that a name and schema are required
```

## FastMCP Parity
- **FastMCP**: `mcp.add_tool(fn)` / `mcp.local_provider.remove_tool(name)` — functions are registered/removed by reference or name. List-changed notifications sent automatically.
- **NestJS**: `McpRegistryService.registerTool(instance, methodName, options)` / `unregisterTool(name)` — uses instance+method pattern consistent with NestJS DI. Options allow overriding metadata. Notifications sent via SDK-005.
- **Difference**: FastMCP allows registering bare functions; our approach requires an object instance (for DI compatibility). A standalone function can be wrapped: `registerTool({ handler: fn }, 'handler', { name: '...' })`.

## Dependencies
- **Depends on:** CORE-005 — McpHandlerRegistry (internal add/remove methods)
- **Depends on:** CORE-012 — McpModule configuration (`onDuplicate` setting)
- **Depends on:** SDK-005 — list-changed notifications
- **Blocks:** nothing

## Technical Notes
- `McpRegistryService` is a thin wrapper over `McpHandlerRegistry` + `McpSessionService`. It adds: input validation, `onDuplicate` enforcement, and automatic notification sending.
- The registry's internal `addTool()` must build the same `HandlerRegistryEntry` structure as boot-time discovery, including: `classRef`, `instance`, `methodName`, `ctxParamIndex`, `schemas`, `metadata`. For runtime-registered methods, `ctxParamIndex` is read from `@Ctx()` decorator metadata if present, otherwise `undefined`.
- Notification is sent *after* the registry mutation succeeds (not before, not on error).
- Thread safety: Node.js is single-threaded, so no locking needed. However, if the mutation + notification is `async`, ensure the registry is updated synchronously before the notification `await`.
- File location: `packages/nestjs-mcp/src/services/mcp-registry.service.ts`
