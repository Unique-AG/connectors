# SDK-004: Resource subscriptions -- @Resource({ subscribe: true })

## Summary
Expose the MCP SDK's resource subscription mechanism through `@Resource({ subscribe: true })`. Clients can subscribe to resource URI changes and receive `ResourceUpdatedNotification` when the resource content changes. Tool authors trigger notifications via `ctx.notifyResourceUpdated(uri)` or `McpSessionService.notifyResourceUpdated(sessionId, uri)`.

## Background / Context
The MCP SDK v1.25.2 supports resource subscriptions — clients subscribe to specific resource URIs and receive notifications when those resources change. This enables real-time updates for dynamic resources (configuration changes, inbox updates, live data feeds).

The SDK provides:
- Subscribe/unsubscribe request handlers on the server
- `sendResourceUpdated(uri)` notification method
- Capability advertisement for subscription support

Our framework needs to wire these together with the `@Resource()` decorator and provide ergonomic APIs for triggering notifications.

## Acceptance Criteria
- [ ] `@Resource({ uri: '...', subscribe: true })` advertises subscription support for that resource
- [ ] Framework registers subscribe/unsubscribe handlers with the SDK for subscribable resources
- [ ] Framework tracks which clients/sessions are subscribed to which resource URIs
- [ ] `ctx.notifyResourceUpdated(uri: string)` sends `ResourceUpdatedNotification` to all subscribed clients
- [ ] `McpSessionService.notifyResourceUpdated(uri: string)` broadcasts to all sessions subscribed to that URI
- [ ] `McpSessionService.notifyResourceUpdated(sessionId: string, uri: string)` targets a specific session
- [ ] Clients that unsubscribe stop receiving notifications
- [ ] Session termination automatically cleans up subscriptions
- [ ] Subscription state is in-memory (per-instance) — no persistence needed

## BDD Scenarios

```gherkin
Feature: Resource subscriptions
  Clients can subscribe to resource URI changes and receive
  notifications when resource content is updated.

  Background:
    Given an MCP server with subscribable resources

  Rule: Clients subscribe and receive update notifications

    Scenario: Client subscribes to a resource and receives updates
      Given a subscribable resource at "config://app/settings"
      And an MCP client subscribed to "config://app/settings"
      When the resource "config://app/settings" is updated
      Then the client receives a resource-updated notification for "config://app/settings"
      And re-reading "config://app/settings" returns the new content

    Scenario: Multiple subscribers all receive the notification
      Given a subscribable resource at "inbox://user-123/messages"
      And client A is subscribed to "inbox://user-123/messages"
      And client B is subscribed to "inbox://user-123/messages"
      When the resource "inbox://user-123/messages" is updated
      Then both client A and client B receive a resource-updated notification

  Rule: Unsubscribed and disconnected clients do not receive notifications

    Scenario: Client unsubscribes and stops receiving notifications
      Given a subscribable resource at "config://app/settings"
      And an MCP client subscribed to "config://app/settings"
      When the client unsubscribes from "config://app/settings"
      And the resource "config://app/settings" is updated
      Then the client does not receive a notification

    Scenario: Session termination cleans up subscriptions
      Given an MCP client subscribed to "config://app/settings"
      When the client's session is terminated
      And the resource "config://app/settings" is updated
      Then no notification is sent to the terminated session

    Scenario: Disconnected subscriber does not block other subscribers
      Given client A and client B are subscribed to "config://app/settings"
      When client A's connection drops unexpectedly
      And the resource "config://app/settings" is updated
      Then client B still receives the notification
      And the failed notification to client A is logged but does not cause an error

  Rule: Only subscribable resources accept subscriptions

    Scenario: Subscribing to a non-subscribable resource is rejected
      Given a resource at "static://help" that does not support subscriptions
      When an MCP client attempts to subscribe to "static://help"
      Then the subscribe request is rejected with an error

  Rule: Template resources support subscriptions on resolved URIs

    Scenario: Subscription targets the resolved URI, not the template
      Given a subscribable resource template "users://{user_id}/profile"
      And an MCP client subscribed to "users://123/profile"
      When the resource "users://123/profile" is updated
      Then the client receives a notification
      When the resource "users://456/profile" is updated
      Then the client does not receive a notification

  Rule: Resource removal cleans up subscriptions

    Scenario: Subscriptions are cleaned up when a resource is removed
      Given an MCP client subscribed to "data://reports/daily"
      When the resource "data://reports/daily" is removed from the server
      Then the subscription for that URI is cleaned up
```

## FastMCP Parity
FastMCP (Python) supports resource subscriptions via the `subscribe` parameter on `@resource`. Our implementation mirrors this with `@Resource({ subscribe: true })`. FastMCP uses `ctx.notify_resource_updated(uri)` for triggering notifications — we provide both `ctx.notifyResourceUpdated(uri)` and `McpSessionService.notifyResourceUpdated(uri)` for broader flexibility.

## Dependencies
- **Depends on:** CORE-002 (@Resource decorator) — decorator metadata must include `subscribe` flag
- **Depends on:** CORE-013 (McpResourcesHandler) — handler registers subscribe/unsubscribe handlers with the SDK
- **Depends on:** SESS-004 (McpSessionRegistry + McpSessionService) — tracks active sessions for broadcast notifications
- **Blocks:** none

## Technical Notes
- SDK APIs:
  - `server.setRequestHandler(SubscribeRequestSchema, handler)` — handle subscribe requests
  - `server.setRequestHandler(UnsubscribeRequestSchema, handler)` — handle unsubscribe requests
  - `server.sendResourceUpdated(uri)` — send notification on a specific transport/session
- Subscription registry (in-memory):
  ```typescript
  // Maps resource URI -> Set of sessionIds
  private subscriptions = new Map<string, Set<string>>();
  ```
- `ctx.notifyResourceUpdated(uri)` iterates all sessions subscribed to `uri` and calls `sendResourceUpdated` on each session's transport
- For resource templates (`users://{user_id}/profile`), subscriptions are on the resolved URI (e.g., `users://123/profile`), not the template
- Subscription state does NOT survive server restarts — clients must re-subscribe after reconnection. This matches the MCP protocol expectation.
- The `ResourceUpdatedNotification` only tells the client the resource changed — the client must re-read the resource to get the new content. This is by design in the MCP spec.
