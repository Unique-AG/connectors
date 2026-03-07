# CONN-002: Required Connections & Pre-Auth Gate

## Summary
Allow an MCP server to declare which upstream providers users must connect before a session token (MCP JWT) is issued. A connection portal queries the server's `/.well-known/mcp-connections` endpoint to discover requirements and guide users through each OAuth flow. The MCP JWT `extra` field carries a `connectedProviders` list, which tools and guards can inspect without hitting the store on every request.

## Background / Context
For **virtual server** scenarios — where one MCP server aggregates tools from multiple upstream providers (e.g., Microsoft Graph + Google Drive) — it is acceptable and desirable to require all upstream connections upfront. The user visits a connection portal once, authenticates with each required provider, and then receives a single MCP token that works for all tools.

This is **Layer 1** of the hybrid auth strategy:
- All required tokens are collected before the session starts
- The MCP JWT encodes which providers are already connected (`connectedProviders` in `extra`)
- Tool handlers can proceed without triggering OAuth mid-execution
- If a token later expires or is revoked, **Layer 2** (CONN-004/CONN-005) handles the reconnection

The `/.well-known/mcp-connections` endpoint serves as the machine-readable contract between the MCP server and any connection portal (internal, third-party, or AI-agent orchestrator). It lists which providers are required, optional, or blocked, along with human-readable labels and OAuth discovery metadata.

## Acceptance Criteria

### Server-level connection requirements declaration
- [ ] `McpModule.forRoot({ requiredConnections: ['microsoft-graph', 'google-drive'] })` declares mandatory upstream connections
- [ ] `McpModule.forRoot({ optionalConnections: ['slack'] })` declares optional upstream connections (tools degrade gracefully when missing)
- [ ] Connection IDs in `requiredConnections` must correspond to providers registered in `UpstreamProviderRegistry` (CONN-003); startup throws if unknown ID is declared
- [ ] At module init (`OnModuleInit`), `McpConnectionModule` validates that every provider ID listed in `requiredConnections` and `optionalConnections` is registered in `UpstreamProviderRegistry`. If any ID is unrecognized, the application throws: `McpConnectionError: Unknown upstream provider declared in requiredConnections: '{providerId}'. Register it in McpConnectionModule.forRoot({ providers: [...] }) first.`

### Well-known discovery endpoint
- [ ] `GET /.well-known/mcp-connections` returns a JSON document listing all declared connections
- [ ] Response schema:
  ```json
  {
    "requiredConnections": [
      {
        "providerId": "microsoft-graph",
        "displayName": "Microsoft Graph",
        "description": "Access to Outlook email and calendar",
        "authorizationUrl": "/mcp/auth/connect/microsoft-graph",
        "connected": false
      }
    ],
    "optionalConnections": [...]
  }
  ```
- [ ] `connected` field is `false` by default (unauthenticated call); when caller presents a valid MCP token, `connected` reflects actual connection status from the store for that user
- [ ] Endpoint is mounted automatically when `requiredConnections` or `optionalConnections` is non-empty
- [ ] Endpoint is unauthenticated (no MCP token required) so portals can discover requirements before the user has a token

### MCP JWT gate
- [ ] When `McpAuthModule` issues a session token (AUTH-001/AUTH-002 flow), it checks: does the user have live connections for all `requiredConnections`?
- [ ] If any required connection is missing, the token is NOT issued; the response includes `{ error: 'connections_required', missing: ['microsoft-graph'] }` and the `authorizationUrl` for each missing provider
- [ ] If all required connections are present, the JWT `extra` field includes `{ connectedProviders: ['microsoft-graph', 'google-drive'] }`
- [ ] Optional connections that are present are also listed in `connectedProviders`
- [ ] `connectedProviders` in the JWT is used as a fast-path check by guards — avoids a store lookup on every tool call

### McpIdentity extension
- [ ] `McpIdentity.connectedProviders: string[]` — populated from `authInfo.extra.connectedProviders` during identity resolution
- [ ] `ctx.identity.connectedProviders` available in all tool/resource/prompt handlers
- [ ] Empty array when no `connectedProviders` claim is present (backwards compatible)

### Connection status at runtime
- [ ] `McpConnectionService.getConnectionStatus(userId): Promise<ConnectionStatusReport>` returns which providers are connected, connected-but-expiring-soon, or disconnected
- [ ] `McpConnectionService` is `@Injectable()`, exported from `McpConnectionModule`
- [ ] Used by `/.well-known/mcp-connections` when called with a valid user token

## BDD Scenarios

```gherkin
Feature: Required Connections & Pre-Auth Gate
  The server declares which upstream providers users must connect before a
  session token is issued. A connection portal discovers requirements via a
  well-known endpoint and collects OAuth tokens upfront.

  Rule: Server declares required connections

    Scenario: Discovery endpoint lists required connections
      Given the server is configured with required connections "microsoft-graph" and "google-drive"
      When an unauthenticated caller requests GET /.well-known/mcp-connections
      Then the response lists "microsoft-graph" and "google-drive" under requiredConnections
      And each entry includes a displayName, description, and authorizationUrl

    Scenario: Discovery endpoint shows connection status for authenticated user
      Given the server requires connections to "microsoft-graph" and "google-drive"
      And user "alice" has connected "microsoft-graph" but not "google-drive"
      When "alice" requests GET /.well-known/mcp-connections with her MCP token
      Then the "microsoft-graph" entry has connected: true
      And the "google-drive" entry has connected: false

  Rule: MCP JWT is not issued until all required connections are present

    Scenario: Token issuance blocked when a required connection is missing
      Given the server requires a connection to "microsoft-graph"
      And user "alice" has not connected "microsoft-graph"
      When "alice" requests a session token
      Then the token is not issued
      And the response includes error "connections_required"
      And the response lists "microsoft-graph" as missing with its authorizationUrl

    Scenario: Token is issued once all required connections are present
      Given the server requires connections to "microsoft-graph" and "google-drive"
      And user "alice" has connected both providers
      When "alice" requests a session token
      Then the token is issued
      And the token's extra field includes connectedProviders containing "microsoft-graph" and "google-drive"

    Scenario: Optional connection absence does not block token issuance
      Given the server requires "microsoft-graph" and has "slack" as optional
      And user "alice" has connected "microsoft-graph" but not "slack"
      When "alice" requests a session token
      Then the token is issued
      And connectedProviders contains "microsoft-graph" but not "slack"

  Rule: McpIdentity reflects connected providers from the JWT

    Scenario: Tool handler can inspect connected providers
      Given a tool that reads ctx.identity.connectedProviders
      And the caller's token includes connectedProviders "microsoft-graph" and "google-drive"
      When the tool is called
      Then ctx.identity.connectedProviders equals ["microsoft-graph", "google-drive"]

    Scenario: No connectedProviders claim results in empty array
      Given a token issued without the connectedProviders claim
      When a tool reads ctx.identity.connectedProviders
      Then the value is an empty array

    Scenario: Mid-session optional connection is accessible without JWT update
      Given "alice"'s token lists connectedProviders ["microsoft-graph"]
      And "alice" connects "slack" mid-session via elicitation
      When a tool calls upstream.getToken("slack")
      Then the token is returned from the connection store
      Even though "slack" is not in ctx.identity.connectedProviders

  Rule: Unknown provider IDs cause startup failure

    Scenario: Undeclared provider in requiredConnections fails at startup
      Given the server declares required connection "acme-provider"
      And "acme-provider" is not registered in the UpstreamProviderRegistry
      When the application starts
      Then an error is thrown: "Unknown upstream provider: acme-provider"
```

## FastMCP Parity
FastMCP (Python) does not have a built-in multi-provider pre-auth gate; its proxy creates separate server instances per upstream. Our `requiredConnections` approach is inspired by Composio's connection portal and Zapier's connected apps model — users connect integrations once via a portal before using any tools.

## Dependencies
- **Depends on:** CONN-001 (UpstreamConnectionStore — checks which providers are connected)
- **Depends on:** CONN-003 (UpstreamProviderRegistry — validates declared provider IDs)
- **Depends on:** AUTH-001/AUTH-002 (McpAuthModule — token issuance gate hooks in here)
- **Blocks:** CONN-004 (guard reads `connectedProviders` from McpIdentity for fast-path)

## Technical Notes
- The `/.well-known/mcp-connections` endpoint is part of MCP service discovery — register it as a standard `@Controller()` (not raw middleware)
- The JWT gate is implemented as a hook in `McpAuthModule.issueToken()` — not as a separate guard, since the check must happen before the token exists
- The `connectedProviders` array in the JWT is a snapshot taken at token-issuance time. It does NOT update when the user acquires additional optional connections mid-session via the elicitation flow (CONN-005). Mid-session connections are stored in `McpConnectionStore` and accessible via `UpstreamTokenService.getToken()` even if not listed in the JWT. The JWT claim is only used as a fast-path check by `McpConnectionGuard` to avoid store lookups for required connections. Guards always fall back to a store lookup when the JWT claim is absent.
- For virtual server scenarios, `requiredConnections` is the correct mechanism. For servers where tools optionally use upstream providers, use `optionalConnections` + `@RequiresConnection` (CONN-004) which will trigger elicitation lazily
