# CONN-005: Runtime Reconnection via Elicitation

## Summary
Implement the reconnection pipeline that catches `UpstreamConnectionRequiredError` (thrown by CONN-004's `McpConnectionGuard` or by `UpstreamTokenService.getToken()`) and triggers an MCP URL elicitation to guide the user through re-authorizing the affected upstream provider. Once the OAuth callback completes (CONN-003), the tool is retried automatically.

## Background / Context
This is **Layer 2** of the hybrid auth strategy — the safety net that activates when a previously valid connection becomes invalid mid-session. The trigger conditions are:

1. **Expired + unrefreshable**: Access token expired and refresh token was revoked
2. **Permission change**: User revoked the app's access in the upstream provider's settings
3. **Optional provider**: Tool requires a provider not connected at session start (not in `requiredConnections`)
4. **First time**: User is calling a tool with `@RequiresConnection` but hasn't gone through the portal yet

The reconnection flow uses MCP's **URL elicitation** (`server.elicitInput({ mode: 'url' })`) to push the OAuth URL to the client. The client opens a browser, the user re-authenticates, the callback (CONN-003) stores fresh tokens, and `createElicitationCompletionNotifier` signals the waiting tool handler to retry.

This flow integrates naturally with the existing pipeline runner (CORE-010): `UpstreamConnectionRequiredError` is caught in the pipeline's error handler, not in the tool handler itself, keeping tool code clean.

## Acceptance Criteria

### McpReconnectionPipeline (pipeline component, opt-in)
- [ ] `McpReconnectionPipeline` is a pipeline component (CORE-011 style) that wraps tool execution
- [ ] Catches `UpstreamConnectionRequiredError` thrown anywhere during tool execution (including from guard or from `upstream.getToken()` in the handler)
- [ ] On catch: initiates the elicitation flow (see below)
- [ ] If elicitation completes successfully: retries the original tool call **once** (not indefinitely)
- [ ] If the retry throws `UpstreamConnectionRequiredError` again: returns an MCP error result with code `connection_failed` — does NOT loop
- [ ] If elicitation is declined/cancelled by the user: returns an MCP error result with code `connection_declined`
- [ ] Registered as an opt-in pipeline component: `McpModule.forRoot({ pipeline: [McpReconnectionPipeline, ...] })`

### Elicitation trigger
- [ ] Calls `server.elicitInput({ mode: 'url', url: oauthUrl, message: 'Please reconnect your ${displayName} account to continue', elicitationId })` where:
  - `oauthUrl` is built by `UpstreamProviderRegistry.buildAuthorizationUrl(providerId, callbackUri, state)` with the elicitation ID encoded in `state`
  - `elicitationId` is a fresh UUID
  - `message` uses the provider's `displayName` from the registry
- [ ] The OAuth callback (CONN-003) calls `createElicitationCompletionNotifier(elicitationId)` after storing tokens
- [ ] `McpReconnectionPipeline` awaits the completion notifier (with a configurable timeout, default: 5 minutes)
- [ ] On timeout: returns MCP error result with code `connection_timeout`

### Elicitation result handling
- [ ] `elicitInput` result with `action: 'completed'` → proceed to retry
- [ ] `elicitInput` result with `action: 'declined'` → return `{ isError: true, content: [{ type: 'text', text: 'Connection to {displayName} was declined' }] }`
- [ ] `elicitInput` result with `action: 'error'` → return `{ isError: true, content: [{ type: 'text', text: 'Connection to {displayName} failed: {reason}' }] }`

### Client capability check
- [ ] Before triggering elicitation, check whether the connected MCP client supports URL elicitation (via `server.getClientCapabilities().elicitation?.urlMode`)
- [ ] If the client does NOT support URL elicitation: skip the elicitation, return a descriptive MCP error result: `{ isError: true, content: [{ type: 'text', text: 'This tool requires a connection to {displayName}. Please reconnect via the connection portal at {wellKnownUrl}' }] }`
- [ ] The fallback message includes the well-known URL (`/.well-known/mcp-connections`) so the user knows where to reconnect out-of-band

### Reconnection event hooks
- [ ] `McpConnectionModule` emits Node.js `EventEmitter` events for observability:
  - `'connection.required'` — `{ userId, providerId }` — when reconnection is triggered
  - `'connection.restored'` — `{ userId, providerId }` — when reconnection completes successfully
  - `'connection.failed'` — `{ userId, providerId, reason }` — when reconnection fails
- [ ] Event emitter is injectable: `constructor(@Inject(MCP_CONNECTION_EVENTS) private events: EventEmitter)`

### Integration with McpProxyModule (CORE-017 extension)
- [ ] When a proxied tool call returns HTTP 401 from the upstream: the proxy handler catches it and throws `UpstreamConnectionRequiredError(upstreamName)` — the same pipeline picks it up
- [ ] This makes CORE-017's `upstreamAuth` function the connection store lookup: `upstreamAuth: async (upstreamName, identity) => connectionStore.require(identity.userId, upstreamName)`

## BDD Scenarios

```gherkin
Feature: Runtime Reconnection via Elicitation
  When a tool call fails because an upstream connection is missing or expired,
  the framework triggers a URL elicitation to guide the user through re-authorizing
  the provider, then retries the tool automatically.

  Rule: Expired connection triggers URL elicitation and retries

    Scenario: Tool succeeds after user reconnects an expired connection
      Given user "alice" calls tool "list_emails" which requires "microsoft-graph"
      And "alice"'s "microsoft-graph" token has expired and the refresh token is revoked
      When the tool is called
      Then the pipeline catches UpstreamConnectionRequiredError for "microsoft-graph"
      And the client receives a URL elicitation pointing to the Microsoft OAuth page
      When "alice" completes the OAuth flow in her browser
      Then the callback stores fresh tokens and signals the elicitation as complete
      And the pipeline retries "list_emails"
      And the tool result is returned to the client

    Scenario: Tool returns connection_declined when user cancels the OAuth flow
      Given "alice" calls a tool requiring "slack"
      And her Slack token is expired
      When the URL elicitation is sent and "alice" declines it
      Then the tool returns an error result: "Connection to Slack was declined"

    Scenario: Elicitation timeout returns a connection_timeout error
      Given a tool requiring "google-drive" with an expired token
      And the user does not complete the OAuth flow within 5 minutes
      When the elicitation times out
      Then the tool returns an error result indicating the connection timed out

    Scenario: One retry after reconnection — no infinite loop
      Given "alice" reconnects "microsoft-graph" via elicitation
      But the retry still throws UpstreamConnectionRequiredError (e.g., wrong scopes granted)
      Then the pipeline returns an error result with code "connection_failed"
      And no further elicitation is triggered

  Rule: Clients without elicitation support receive a portal fallback message

    Scenario: Non-elicitation client gets an actionable error message
      Given an MCP client that does not support URL mode elicitation
      And user "alice" calls a tool requiring "microsoft-graph" with no live connection
      When the tool is called
      Then the tool returns an error result containing:
        - A message explaining the connection is required
        - The URL to the well-known connections endpoint for out-of-band reconnection

  Rule: Proxied tools follow the same reconnection flow

    Scenario: Upstream HTTP 401 on a proxied tool triggers reconnection
      Given a proxied tool "weather_get_forecast" from upstream "weather-service"
      And the upstream returns HTTP 401 (token expired)
      When "alice" calls "weather_get_forecast"
      Then the proxy throws UpstreamConnectionRequiredError for "weather-service"
      And the reconnection pipeline triggers URL elicitation for "weather-service"

  Rule: Connection events are emitted for observability

    Scenario: Successful reconnection emits restored event
      Given a listener on the "connection.restored" event
      When "alice" successfully reconnects "microsoft-graph" via elicitation
      Then the "connection.restored" event is emitted with userId "alice" and providerId "microsoft-graph"

    Scenario: Failed reconnection emits failed event
      Given a listener on the "connection.failed" event
      When "alice"'s reconnection attempt for "slack" times out
      Then the "connection.failed" event is emitted with reason "timeout"

  Rule: Optional connections can be acquired lazily without a pre-auth gate

    Scenario: Tool with optional connection works for users who haven't connected yet
      Given "carol" has never connected "slack" (it is an optional connection, not required)
      And a tool "post_slack_message" with @RequiresConnection("slack")
      When "carol" calls "post_slack_message" for the first time
      Then the reconnection pipeline triggers URL elicitation for Slack
      And after "carol" completes OAuth, the tool executes successfully
      And future calls by "carol" to "post_slack_message" proceed without elicitation
```

## FastMCP Parity
FastMCP (Python) does not implement mid-session reconnection via elicitation. This is a novel capability enabled by the MCP 2025-11-25 URL elicitation spec. Our implementation extends beyond FastMCP's feature set.

## Dependencies
- **Depends on:** CONN-001 (McpConnectionStore — stores tokens after callback)
- **Depends on:** CONN-003 (UpstreamProviderRegistry — builds OAuth URL for elicitation; callback triggers completion notifier)
- **Depends on:** CONN-004 (McpConnectionGuard throws UpstreamConnectionRequiredError; UpstreamTokenService re-throws it from handler code)
- **Depends on:** CORE-010 (pipeline runner — McpReconnectionPipeline is a pipeline component)
- **Depends on:** SDK-002 or equivalent (elicitation API — `server.elicitInput()` and `createElicitationCompletionNotifier()`)
- **Blocks:** none

## Technical Notes
- `McpReconnectionPipeline` is intentionally opt-in, not default. Elicitation requires client support, and not all deployments will want auto-reconnect behavior. For purely pre-auth virtual server scenarios (CONN-002 only), skip this pipeline component entirely.
- The `elicitationId` encodes as part of the OAuth `state` JWT (CONN-003) so the callback knows which elicitation to complete. This is why the elicitation ID must be generated before building the authorization URL.
- Retry is "once only" to prevent thrashing. If the problem persists after one reconnection (e.g., user granted wrong scopes), the error is surfaced immediately rather than looping.
- For the proxy integration: `CORE-017` upstream auth function becomes `(upstreamName, identity) => upstreamTokenService.getToken(upstreamName)` — the proxy never holds tokens directly; it always fetches from the connection store per-request. This means `sessionMode: 'isolated'` (CORE-017) remains the correct default.
- Elicitation timeout (default 5 minutes) should be configurable: `McpModule.forRoot({ reconnectionTimeoutMs: 300_000 })`
