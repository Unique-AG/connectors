# CORE-029: Proxy Feature Forwarding

## Summary
Forward upstream MCP feature notifications and requests through the proxy to the downstream client session. Covers progress notifications, logging messages, roots requests, sampling requests, and elicitation requests. Each forwarding type is conditional on the downstream client advertising support for the capability.

## Background / Context
When a proxy forwards tool calls to an upstream MCP server, the upstream may emit progress notifications, logging messages, or initiate roots/sampling/elicitation requests back to the client. Without forwarding, these are silently dropped, degrading the user experience for proxied tools that rely on these features (e.g., long-running tools with progress bars, tools that need user confirmation via elicitation).

This was originally part of CORE-017 but was split out to keep the core proxy module focused on basic proxying while this ticket handles the advanced forwarding layer.

## Acceptance Criteria

### Progress forwarding
- [ ] When an upstream tool emits a `notifications/progress` notification during execution, the proxy forwards it to the downstream client session via `McpSessionService`
- [ ] Progress token mapping: the proxy maps upstream progress tokens to downstream progress tokens (the downstream client's `_meta.progressToken`)
- [ ] If the downstream client did not provide a `progressToken` in the original request, upstream progress notifications are silently dropped

### Logging forwarding
- [ ] When an upstream server sends a `notifications/message` (logging) notification, the proxy forwards it to the downstream client
- [ ] The forwarded log message includes the upstream server name as a prefix in the `logger` field (e.g., `weather: upstream-logger-name`)
- [ ] Logging level is preserved as-is from upstream

### Roots request forwarding
- [ ] When an upstream server sends a `roots/list` request, the proxy forwards it to the downstream client
- [ ] Only forwarded if the downstream client advertised `roots` capability during initialization
- [ ] If the downstream client does not support roots, the proxy responds with an empty roots list

### Sampling request forwarding
- [ ] When an upstream server sends a `sampling/createMessage` request, the proxy forwards it to the downstream client
- [ ] Only forwarded if the downstream client advertised `sampling` capability during initialization
- [ ] If the downstream client does not support sampling, the proxy returns `McpError(MethodNotFound)`

### Elicitation request forwarding
- [ ] When an upstream server sends an `elicitation/create` request, the proxy forwards it to the downstream client
- [ ] Only forwarded if the downstream client advertised `elicitation` capability during initialization
- [ ] If the downstream client does not support elicitation, the proxy returns `McpError(MethodNotFound)`

### Capability check
- [ ] Before forwarding any request/notification, the proxy checks the downstream client's capabilities from the session initialization handshake
- [ ] Missing capability results in graceful fallback (drop notification or return error), never an unhandled exception

## BDD Scenarios

```gherkin
Feature: Proxy Feature Forwarding
  The proxy forwards upstream notifications and requests to the downstream
  client session, enabling rich interaction through proxied tools.

  Rule: Progress notification forwarding

    Scenario: Upstream progress is forwarded to the downstream client
      Given a proxied tool that emits progress notifications during execution
      And the downstream client provided a progress token in the tool call
      When a client calls the proxied tool
      Then progress notifications from the upstream are delivered to the client in real time
      And the progress token maps to the downstream client's token

    Scenario: Progress is dropped when no progress token was provided
      Given a proxied tool that emits progress notifications
      And the downstream client did not provide a progress token
      When a client calls the proxied tool
      Then upstream progress notifications are silently dropped

  Rule: Logging message forwarding

    Scenario: Upstream logging messages are forwarded with server name prefix
      Given a proxy configured with upstream server named "weather"
      And the upstream emits a logging message with logger "forecast-service" at level "info"
      When the proxy receives the logging notification
      Then the downstream client receives a logging message with logger "weather: forecast-service" at level "info"

  Rule: Roots request forwarding

    Scenario: Roots request is forwarded when client supports roots
      Given a downstream client that advertised roots capability
      And the upstream server sends a roots/list request
      When the proxy receives the roots request
      Then the request is forwarded to the downstream client
      And the upstream receives the client's roots response

    Scenario: Roots request returns empty list when client does not support roots
      Given a downstream client that did not advertise roots capability
      And the upstream server sends a roots/list request
      When the proxy receives the roots request
      Then the upstream receives an empty roots list

  Rule: Sampling request forwarding

    Scenario: Sampling request is forwarded when client supports sampling
      Given a downstream client that advertised sampling capability
      And the upstream server sends a sampling/createMessage request
      When the proxy receives the sampling request
      Then the request is forwarded to the downstream client
      And the upstream receives the client's sampling response

    Scenario: Sampling request returns error when client does not support sampling
      Given a downstream client that did not advertise sampling capability
      And the upstream server sends a sampling/createMessage request
      When the proxy receives the sampling request
      Then the upstream receives a MethodNotFound error

  Rule: Elicitation request forwarding

    Scenario: Elicitation request is forwarded when client supports elicitation
      Given a downstream client that advertised elicitation capability
      And the upstream server sends an elicitation/create request
      When the proxy receives the elicitation request
      Then the request is forwarded to the downstream client
      And the upstream receives the client's elicitation response

    Scenario: Elicitation request returns error when client does not support elicitation
      Given a downstream client that did not advertise elicitation capability
      And the upstream server sends an elicitation/create request
      When the proxy receives the elicitation request
      Then the upstream receives a MethodNotFound error
```

## Dependencies
- **Depends on:** CORE-017 (McpProxyModule core) — the proxy infrastructure and upstream client management
- **Depends on:** SESS-004 (McpSessionService) — session context for accessing downstream client capabilities and sending notifications
- **Depends on:** SDK-001 (ctx.elicit) — elicitation protocol support
- **Depends on:** SDK-002 (ctx.sample) — sampling protocol support
- **Blocks:** none

## Technical Notes
- Each forwarding type registers a notification/request handler on the upstream `Client` instance
- Progress token mapping is maintained in a per-call `Map<upstream_token, downstream_token>` that is cleaned up after the call completes
- Logging prefix format: `{upstreamName}: {originalLogger}` — if upstream has no logger name, just use `{upstreamName}`
- Capability detection: read `clientCapabilities` from `McpSessionService.getSession(sessionId)` which stores the capabilities from the `initialize` handshake
- For roots/sampling/elicitation forwarding, the proxy acts as a "pass-through" — it does not modify the request/response payloads, only routes them between upstream and downstream
- File locations:
  - `packages/nestjs-mcp/src/proxy/forwarding/progress-forwarder.ts`
  - `packages/nestjs-mcp/src/proxy/forwarding/logging-forwarder.ts`
  - `packages/nestjs-mcp/src/proxy/forwarding/capability-forwarder.ts` (roots, sampling, elicitation)
