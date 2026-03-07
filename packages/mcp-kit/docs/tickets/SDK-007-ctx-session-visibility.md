# SDK-007: ctx.enableComponents / ctx.disableComponents — Per-Session Visibility

## Summary
Implement per-session component visibility control accessible from within tool, resource, and prompt handlers via `McpContext`. This allows tools to dynamically show/hide other tools, resources, and prompts for the current session (e.g., revealing advanced tools after authentication, hiding admin tools from unprivileged sessions).

## Background / Context
FastMCP v3.0.0 introduces per-session visibility control: `ctx.enableComponents(keys)`, `ctx.disableComponents(keys)`, `ctx.resetVisibility()`. This enables dynamic MCP server surfaces that adapt based on session state — for example, an authentication tool that reveals admin tools after successful login, or a wizard that progressively discloses steps.

In our framework, visibility overrides are session-scoped and stored in `McpSessionRecord.visibilityOverrides`. The server-level tag-based filtering (CORE-015) serves as the base layer; session-level overrides are applied on top. When a component is disabled at session level, it is excluded from `listTools`/`listResources`/`listPrompts` responses and cannot be invoked.

STDIO transport has no session concept, so calling visibility methods on STDIO connections throws a descriptive error.

## Acceptance Criteria
- [ ] `ctx.disableComponents(keys: string[]): Promise<void>` — adds keys to session-level disable set; components matching these keys are hidden from list responses and cannot be invoked
- [ ] Key format: `"tool:<tool_name>"`, `"resource:<uri>"`, `"prompt:<prompt_name>"` — type prefix is required
- [ ] `ctx.enableComponents(keys: string[]): Promise<void>` — removes keys from the disable set (re-enables previously disabled components)
- [ ] `ctx.resetVisibility(): Promise<void>` — clears all session-level visibility overrides, falling back to server-level config (CORE-015 tags)
- [ ] Visibility state is session-scoped: stored in `McpSessionRecord.visibilityOverrides`
- [ ] `McpSessionRecord` interface updated with `visibilityOverrides: { disabled: Set<string> }` field (defaults to `{ disabled: new Set() }`)
- [ ] `McpToolsHandler.listTools()` checks session-level overrides on top of server-level tag filtering before returning results
- [ ] `McpResourcesHandler.listResources()` and `McpPromptsHandler.listPrompts()` similarly check session-level overrides
- [ ] Invoking a disabled tool/resource/prompt returns `McpError(MethodNotFound)` with descriptive message
- [ ] Invalid key format (missing type prefix) throws `McpError(InvalidParams)` with message explaining the required format
- [ ] For STDIO transport: calling any visibility method throws `McpError(InvalidRequest)` with message "Session visibility is not available on STDIO transport."
- [ ] After disabling/enabling components, the server sends a `notifications/tools/list_changed` (or resources/prompts equivalent) to notify the client

## BDD Scenarios

```gherkin
Feature: Per-session component visibility
  Tools can dynamically show or hide other tools, resources, and prompts
  for the current session, adapting the server surface at runtime.

  Background:
    Given an MCP server with tools "search", "admin_delete", and "admin_reset"
    And a resource at "config://public" and a resource at "config://secret"
    And a connected MCP client over Streamable HTTP

  Rule: Disabling components hides them from list responses

    Scenario: Disabled tools are hidden from listTools
      Given a tool "login" that disables "admin_delete" and "admin_reset" for the session
      When an MCP client calls "login"
      And then calls listTools
      Then the response contains "search" and "login"
      And "admin_delete" and "admin_reset" are not listed

    Scenario: Disabled resources are hidden from listResources
      Given a tool "restrict_access" that disables the resource "config://secret" for the session
      When an MCP client calls "restrict_access"
      And then calls listResources
      Then only "config://public" is listed

  Rule: Re-enabling and resetting restores visibility

    Scenario: Re-enabling a disabled tool makes it visible again
      Given "admin_delete" was previously disabled for the session
      And a tool "grant_access" that re-enables "admin_delete" for the session
      When an MCP client calls "grant_access"
      And then calls listTools
      Then "admin_delete" is listed in the response

    Scenario: Resetting visibility restores all server-level defaults
      Given "admin_delete" and "config://secret" were disabled for the session
      And a tool "full_reset" that resets all visibility overrides
      When an MCP client calls "full_reset"
      And then calls listTools and listResources
      Then all server-level components are listed

  Rule: Disabled components cannot be invoked

    Scenario: Calling a disabled tool returns a not-found error
      Given "admin_delete" is disabled for the session
      When an MCP client calls "admin_delete"
      Then the client receives an error indicating the tool is not available in this session

  Rule: Visibility changes trigger list-changed notifications

    Scenario: Client is notified when tools are disabled
      Given an MCP client connected to the server
      When a tool disables "admin_delete" for the session
      Then the client receives a tools list-changed notification

  Rule: STDIO transport does not support session visibility

    Scenario: Visibility methods fail on STDIO transport
      Given a connected MCP client over STDIO transport
      And a tool "restrict" that disables components for the session
      When an MCP client calls "restrict"
      Then the tool receives an error indicating visibility requires a session-based transport

  Rule: Component keys must include a type prefix

    Scenario: Key without type prefix is rejected
      Given a tool "bad_disable" that disables "admin_delete" without a type prefix
      When an MCP client calls "bad_disable"
      Then the tool receives a validation error explaining the required key format
```

## Dependencies
- **Depends on:** CORE-007 — McpContext (visibility methods are added to McpContext)
- **Depends on:** SESS-001 — McpSessionRecord needs `visibilityOverrides` field
- **Depends on:** CORE-013 — handlers must check session visibility when building list responses
- **Depends on:** CORE-015 — server-level tag-based filtering is the base layer; session overrides are applied on top
- **Blocks:** nothing directly

## Technical Notes
- `visibilityOverrides` stored in `McpSessionRecord`:
  ```typescript
  interface McpSessionRecord {
    // ... existing fields ...
    visibilityOverrides: {
      disabled: Set<string>;   // set of "type:name" keys
    };
  }
  ```
- For serialization to Redis/Drizzle, `Set<string>` is converted to `string[]` during persistence and back to `Set` on load
- Key format validation regex: `/^(tool|resource|prompt):.+$/` — must have type prefix followed by colon and name
- `disableComponents` adds to the `disabled` set; `enableComponents` removes from it; `resetVisibility` clears the set
- Handler list methods (CORE-013) must filter after server-level tag filtering: `registeredItems.filter(item => !sessionOverrides.disabled.has(keyFor(item)))`
- Tool invocation must also check visibility: if `disabled.has("tool:" + toolName)`, return `McpError(MethodNotFound)`
- After any visibility change, send the appropriate list-changed notification via SDK so clients can refresh their tool/resource/prompt lists
- `ctx.disableComponents/enableComponents/resetVisibility` delegate to `McpSessionService` methods that update the session record and trigger notifications
- **FastMCP parity:** Maps directly to FastMCP's `ctx.enable_server_components(keys)`, `ctx.disable_server_components(keys)`, and `ctx.reset_server_component_visibility()`. FastMCP uses the same key format pattern. Our implementation adds persistence support via `McpSessionStore` and integrates with server-level tag filtering (CORE-015) as the base layer
- File location: Visibility methods in `packages/nestjs-mcp/src/context/mcp-context.ts`; session record update in `packages/nestjs-mcp/src/session/mcp-session-record.ts`; filtering logic in `packages/nestjs-mcp/src/handlers/`
