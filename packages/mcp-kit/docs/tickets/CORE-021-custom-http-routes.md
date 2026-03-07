# CORE-021: Custom HTTP routes alongside MCP endpoint

## Summary
Enable and document the pattern for serving custom HTTP endpoints (health checks, status pages, webhooks) alongside the MCP endpoint, and provide a built-in optional `McpHealthController` activated via `McpModule.forRoot({ healthCheck: true })`.

## Background / Context
FastMCP supports `@mcp.custom_route("/health", methods=["GET"])` decorator for auxiliary HTTP endpoints served alongside the MCP endpoint. Common uses include health checks, readiness probes for Kubernetes, status pages, and webhook receivers.

In NestJS, this is naturally supported — standard NestJS controllers with `@Get()`, `@Post()` etc. are served on the same host as the MCP endpoint. However, this pattern should be explicitly documented and made easy. This ticket adds a built-in optional health check controller that consumers can enable with a single config flag, and documents how to add custom routes alongside MCP.

## Acceptance Criteria
- [ ] `healthCheck` option added to `McpOptions`: accepts `boolean | McpHealthCheckOptions`
- [ ] `McpHealthCheckOptions` interface: `{ path?: string; extraInfo?: () => Record<string, unknown> | Promise<Record<string, unknown>> }`
- [ ] When `healthCheck: true`, a `GET /mcp/health` endpoint is registered returning `{ status: 'ok', serverName: string, serverVersion: string, uptime: number }`
- [ ] When `healthCheck: { path: '/custom-health' }`, the health endpoint is available at that path instead
- [ ] When `healthCheck: { extraInfo: () => ({ db: 'connected' }) }`, the extra info is merged into the response
- [ ] Health check endpoint returns HTTP 200 with `Content-Type: application/json`
- [ ] Health check endpoint does NOT require MCP authentication (it sits outside the MCP pipeline)
- [ ] `McpHealthController` is conditionally registered — only when `healthCheck` is truthy
- [ ] Standard NestJS controllers in the same application work alongside the MCP endpoint without interference
- [ ] `uptime` is reported in seconds since server start (integer)

## BDD Scenarios

```gherkin
Feature: Custom HTTP routes alongside MCP endpoint
  The MCP server can serve auxiliary HTTP endpoints such as health checks
  alongside the MCP protocol endpoint, without interference.

  Rule: Built-in health check endpoint

    Scenario: Health check is available at the default path when enabled
      Given an MCP server named "my-mcp" version "1.0.0" with health check enabled
      When a GET request is sent to /mcp/health
      Then the response status is 200
      And the response body contains "status" equal to "ok"
      And the response body contains "serverName" equal to "my-mcp"
      And the response body contains "serverVersion" equal to "1.0.0"
      And the response body contains "uptime" as a number

    Scenario: Health check uses a custom path when configured
      Given an MCP server with health check path set to "/healthz"
      When a GET request is sent to /healthz
      Then the response status is 200
      And the response body contains "status" equal to "ok"
      When a GET request is sent to /mcp/health
      Then the response status is 404

    Scenario: Health check includes extra application info
      Given an MCP server with health check configured to report database and redis status
      And the database status is "connected"
      And the redis status is "connected"
      When a GET request is sent to /mcp/health
      Then the response body contains "database" equal to "connected"
      And the response body contains "redis" equal to "connected"

    Scenario: Health check reflects the configured server identity
      Given an MCP server named "email-tools" version "2.1.0" with health check enabled
      When a GET request is sent to /mcp/health
      Then the response body contains "serverName" equal to "email-tools"
      And the response body contains "serverVersion" equal to "2.1.0"

    Scenario: No health endpoint when health check is not enabled
      Given an MCP server with health check not configured
      When a GET request is sent to /mcp/health
      Then the response status is 404

    Scenario: Health check does not require MCP authentication
      Given an MCP server with health check enabled and bearer token authentication configured
      When a GET request is sent to /mcp/health without an Authorization header
      Then the response status is 200

  Rule: Standard application routes coexist with the MCP endpoint

    Scenario: Custom application routes work alongside MCP
      Given an MCP server is running
      And the application has a custom GET /api/status endpoint returning { "ok": true }
      When a GET request is sent to /api/status
      Then the response body contains "ok" equal to true
      When an MCP protocol message is sent to the MCP endpoint
      Then the MCP server processes it normally
```

## FastMCP Parity
- **FastMCP**: `@mcp.custom_route("/health", methods=["GET"])` decorator on functions — registers arbitrary HTTP routes on the same server.
- **NestJS**: Standard NestJS controllers provide the same capability natively. The built-in `McpHealthController` covers the most common use case (health check) with zero custom code. For other custom routes, consumers use standard `@Controller()` + `@Get()` / `@Post()` — no special MCP integration needed.
- **Difference**: FastMCP's `@custom_route` is MCP-specific; in NestJS, this is just regular NestJS controller routing. Our approach is more idiomatic and leverages the full NestJS ecosystem (middleware, guards, etc.) for custom routes.

## Dependencies
- **Depends on:** CORE-012 — McpModule configuration (new `healthCheck` option)
- **Blocks:** nothing

## Technical Notes
- `McpHealthController` implementation:
  ```typescript
  @Controller()
  export class McpHealthController {
    private readonly startTime = Date.now();

    constructor(@Inject(MCP_OPTIONS) private readonly options: McpOptions) {}

    @Get() // path set dynamically via module config
    async health() {
      const extra = this.options.healthCheck?.extraInfo
        ? await this.options.healthCheck.extraInfo()
        : {};
      return {
        status: 'ok',
        serverName: this.options.name,
        serverVersion: this.options.version,
        uptime: Math.floor((Date.now() - this.startTime) / 1000),
        ...extra,
      };
    }
  }
  ```
- The controller path is set dynamically: when `healthCheck` is `true`, use the `mcpEndpoint` prefix + `/health` (default: `/mcp/health`). When `healthCheck.path` is provided, use that exact path.
- Conditional registration: In `McpModule.forRoot()`, only include `McpHealthController` in the `controllers` array when `healthCheck` is truthy. Use `RouterModule.register()` or dynamic controller path assignment.
- The health endpoint must be excluded from any global MCP guards/interceptors. Since it's a standard NestJS controller outside the MCP pipeline, this should be automatic — MCP guards only apply to MCP protocol handlers (CORE-013).
- `McpOptions` update: Add `healthCheck?: boolean | McpHealthCheckOptions` to the interface in CORE-012.
- File location: `packages/nestjs-mcp/src/controllers/mcp-health.controller.ts`
