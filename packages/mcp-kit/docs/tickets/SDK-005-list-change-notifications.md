# SDK-005: List change notifications

## Summary
Expose the MCP SDK's list change notification methods (`sendToolListChanged()`, `sendResourceListChanged()`, `sendPromptListChanged()`) through `McpSessionService`, enabling servers to notify all connected clients when the available tools, resources, or prompts change at runtime.

## Background / Context
The MCP protocol supports notifications that tell clients the server's available capabilities have changed. When a client receives a list-changed notification, it re-fetches the corresponding list (tools, resources, or prompts) to discover additions, removals, or modifications. This is useful for dynamic tool registration, feature flags that enable/disable tools, and multi-tenant scenarios where available tools change based on runtime state.

The SDK provides `sendToolListChanged()`, `sendResourceListChanged()`, and `sendPromptListChanged()` methods on the server. These need to be broadcast to all active sessions.

## Acceptance Criteria
- [ ] `McpSessionService.notifyToolsChanged()` sends `ToolListChangedNotification` to all active sessions
- [ ] `McpSessionService.notifyResourcesChanged()` sends `ResourceListChangedNotification` to all active sessions
- [ ] `McpSessionService.notifyPromptsChanged()` sends `PromptListChangedNotification` to all active sessions
- [ ] Notifications are sent only to sessions with active transports (not to persisted-but-disconnected sessions)
- [ ] Clients that receive the notification can re-fetch the list and see updated entries
- [ ] No error thrown if there are no active sessions (no-op)
- [ ] Notification sending is non-blocking (fire-and-forget, errors logged but not propagated)

## BDD Scenarios

```gherkin
Feature: List change notifications
  The server notifies connected clients when the available
  tools, resources, or prompts change at runtime.

  Rule: All connected clients are notified of list changes

    Scenario Outline: Clients receive list-changed notifications
      Given two MCP clients are connected with active sessions
      When the server broadcasts a <list_type> list-changed notification
      Then both clients receive the notification
      And calling <list_method> returns the updated list

      Examples:
        | list_type | list_method    |
        | tools     | listTools      |
        | resources | listResources  |
        | prompts   | listPrompts    |

    Scenario: Newly registered tools appear after notification
      Given an MCP client is connected
      When new tools are registered via a dynamically loaded module
      And the server broadcasts a tools list-changed notification
      Then the client receives the notification
      And calling listTools returns the newly registered tools

  Rule: Notifications are resilient to session failures

    Scenario: No error when no clients are connected
      Given no MCP clients are currently connected
      When the server broadcasts a tools list-changed notification
      Then no error is thrown

    Scenario: Disconnected sessions are skipped
      Given session "s1" has an active connection and session "s2" is disconnected
      When the server broadcasts a tools list-changed notification
      Then only session "s1" receives the notification
      And session "s2" is skipped without error

    Scenario: One failing session does not block others
      Given sessions "s1", "s2", and "s3" are connected
      When the server broadcasts a tools list-changed notification
      And delivery to session "s2" fails
      Then sessions "s1" and "s3" still receive the notification
      And the failure for "s2" is logged
```

## FastMCP Parity
FastMCP (Python) supports list change notifications through its server lifecycle. Our implementation exposes explicit methods on `McpSessionService` (`notifyToolsChanged()`, `notifyResourcesChanged()`, `notifyPromptsChanged()`) to give consumers control over when notifications are sent. This is more explicit than FastMCP's automatic approach, which is more appropriate for the NestJS ecosystem where dynamic module loading is common.

## Dependencies
- **Depends on:** SESS-004 (McpSessionRegistry + McpSessionService) — session registry tracks active transports; notifications are methods on McpSessionService
- **Depends on:** CORE-013 (McpToolsHandler/ResourcesHandler/PromptsHandler) — server capabilities must advertise `listChanged: true`
- **Blocks:** none

## Technical Notes
- SDK methods: `server.sendToolListChanged()`, `server.sendResourceListChanged()`, `server.sendPromptListChanged()`
- These are per-server-instance calls — in our architecture, each session has its own `McpServer` instance (via the SDK transport model), so we need to iterate all active sessions
- Implementation in `McpSessionService`:
  ```typescript
  notifyToolsChanged(): void {
    for (const [sessionId, transport] of this.registry.getActiveTransports()) {
      try {
        transport.server.sendToolListChanged();
      } catch (err) {
        this.logger.warn({ msg: 'Failed to send tool list changed', sessionId, error: err });
      }
    }
  }
  ```
- Server capabilities must include `{ tools: { listChanged: true }, resources: { listChanged: true }, prompts: { listChanged: true } }` — ensure `McpModule` sets these when registering with the SDK
- Design artifact already shows `notifyToolsChanged()` on `McpSessionService` — this ticket implements it and adds the resource/prompt variants
