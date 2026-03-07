# CORE-011: Built-in pipeline components

## Summary
Implement the built-in pipeline components shipped with the framework: `LoggingInterceptor` (structured logging), `MetricsInterceptor` (OpenTelemetry duration histogram), `RateLimitGuard` (per-operation token bucket), `CachingInterceptor` (TTL-based response caching), `SlidingWindowRateLimitGuard` (precise sliding window rate limiting), `RetryInterceptor` (automatic retry with exponential backoff), and `ResponseLimitingInterceptor` (output size cap). These are opt-in components that consumers register via `McpModule.forRoot()` or standard NestJS DI.

## Background / Context
Built-in pipeline components ship with the framework as standard NestJS `NestInterceptor` and `CanActivate` implementations that work through `ExternalContextCreator` (CORE-010).

These components demonstrate how to write MCP-compatible guards/interceptors using `switchToMcp()` and `getMcpIdentity()`, serving as both useful defaults and documentation-by-example.

FastMCP (Python) ships several built-in middleware components. We provide NestJS-idiomatic equivalents for each.

## Acceptance Criteria

### LoggingInterceptor
- [ ] `LoggingInterceptor` implements `NestInterceptor`
- [ ] Logs on entry: `-> {type}:{name} by {userId|'anon'}`
- [ ] Logs on success: `<- {type}:{name} {duration}ms`
- [ ] Logs on error: `x {type}:{name} {error.message}`
- [ ] Uses NestJS `Logger` with logger name `'MCP'`
- [ ] Skips non-MCP contexts (`context.getType() !== 'mcp'`)

### MetricsInterceptor
- [ ] `MetricsInterceptor` implements `NestInterceptor`
- [ ] Records an OpenTelemetry histogram metric for operation duration
- [ ] Metric name: `mcp.operation.duration` (or similar, configurable)
- [ ] Attributes: `mcp.operation.type`, `mcp.operation.name`, `mcp.status` (success/error)
- [ ] Skips non-MCP contexts

### RateLimitGuard (token bucket)
- [ ] `RateLimitGuard` implements `CanActivate`
- [ ] Per-operation token bucket rate limiting
- [ ] Configurable via decorator or injection: max tokens, refill rate
- [ ] Identifies caller by `identity.userId` (or IP fallback for unauthenticated)
- [ ] Returns `false` (or throws `HttpException(429)`) when rate limit exceeded
- [ ] Skips non-MCP contexts

### CachingInterceptor (FastMCP ResponseCachingMiddleware equivalent)
- [ ] `CachingInterceptor` implements `NestInterceptor`
- [ ] Caches tool/resource responses by `(operationName, JSON.stringify(args))` composite key
- [ ] Configurable TTL per interceptor instance: `new CachingInterceptor({ ttlMs: 60_000 })`
- [ ] Pluggable storage: in-memory `Map` (default) or injectable `CacheStore` interface (compatible with `@nestjs/cache-manager`)
- [ ] Cache key excludes user identity by default (document: user-specific tools should NOT use this interceptor without custom key factory)
- [ ] Optional `keyFactory: (ctx: McpOperationContext) => string` for custom cache keys (can include identity, session, etc.)
- [ ] Cache miss → execute handler → store result; Cache hit → return cached without executing handler
- [ ] Skips non-MCP contexts

### SlidingWindowRateLimitGuard (FastMCP SlidingWindowRateLimitingMiddleware equivalent)
- [ ] `SlidingWindowRateLimitGuard` implements `CanActivate`
- [ ] Sliding window algorithm: tracks timestamps of calls within the window, rejects if count exceeds limit
- [ ] `new SlidingWindowRateLimitGuard({ windowMs: 60_000, maxRequests: 100 })`
- [ ] Keyed by `identity.userId ?? ip` (falls back to IP for unauthenticated)
- [ ] Throws `HttpException(429)` when limit exceeded → error normalization maps to `{ isError: true }` MCP response
- [ ] Skips non-MCP contexts

### RetryInterceptor (FastMCP RetryMiddleware equivalent)
- [ ] `RetryInterceptor` implements `NestInterceptor`
- [ ] `new RetryInterceptor({ maxRetries: 3, backoffMs: 500, backoffMultiplier: 2 })`
- [ ] Catches errors from handler and retries with exponential backoff
- [ ] Only retries on "transient" errors: network errors, 503, `McpError` with retryable codes
- [ ] Does NOT retry `ToolError` (business logic errors should not be retried)
- [ ] After `maxRetries` exhausted → re-throws the original error
- [ ] Skips non-MCP contexts

### ResponseLimitingInterceptor (FastMCP ResponseLimitingMiddleware equivalent)
- [ ] `ResponseLimitingInterceptor` implements `NestInterceptor`
- [ ] `new ResponseLimitingInterceptor({ maxChars: 50_000 })`
- [ ] After handler returns, checks total character length of content blocks
- [ ] If exceeded: truncates content and appends `"[Response truncated: exceeded ${maxChars} character limit]"` message
- [ ] When `outputSchema` is present (structured content), limiting may violate the schema — document: this interceptor should NOT be used with structured output tools, or structured content is dropped and only truncated text content is returned
- [ ] Skips non-MCP contexts

### PingInterceptor (FastMCP PingMiddleware equivalent)
- [ ] `PingInterceptor` implements `NestInterceptor`
- [ ] Keeps long-lived HTTP connections alive by sending SDK ping/keepalive during long-running tool executions
- [ ] Options: `intervalMs: number` (default 30000)
- [ ] Uses `McpServer`'s built-in `ping()` capability to send keepalive pings
- [ ] Starts interval on handler entry, clears on handler completion (success or error)
- [ ] Skips non-MCP contexts

### StructuredLoggingInterceptor (FastMCP StructuredLoggingMiddleware equivalent)
- [ ] `StructuredLoggingInterceptor` implements `NestInterceptor`
- [ ] Extends `LoggingInterceptor` with structured JSON output
- [ ] Output includes: `requestId`, `sessionId`, `operationType`, `operationName`, `latencyMs`, `status` (success/error)
- [ ] Options: `includePayloads: boolean` (default false), `maxPayloadLength: number` (default 500), `logger: Logger` (default NestJS Logger)
- [ ] Skips non-MCP contexts

### TimingInterceptor (FastMCP TimingMiddleware equivalent)
- [ ] `TimingInterceptor` implements `NestInterceptor`
- [ ] Logs execution duration for each operation
- [ ] Log format: `{type}:{name} completed in {duration}ms`
- [ ] Uses NestJS `Logger` with logger name `'MCP.Timing'`
- [ ] Skips non-MCP contexts

### DetailedTimingInterceptor (FastMCP DetailedTimingMiddleware equivalent)
- [ ] `DetailedTimingInterceptor` implements `NestInterceptor`
- [ ] Tracks per-operation-type timing (tools vs resources vs prompts separately)
- [ ] Exposes aggregated timing stats via `getStats()` method: `{ tools: { avgMs, maxMs, count }, resources: { ... }, prompts: { ... } }`
- [ ] Skips non-MCP contexts

### ErrorHandlingInterceptor (FastMCP ErrorHandlingMiddleware equivalent)
- [ ] `ErrorHandlingInterceptor` implements `NestInterceptor`
- [ ] Provides enhanced error reporting (stack traces, custom transformations, error callbacks) as opt-in behavior
- [ ] Options: `includeTraceback: boolean` (default false), `transformErrors: boolean` (default false), `errorCallback: (err: Error) => void`
- [ ] When `includeTraceback` is true, includes stack trace in error response
- [ ] When `errorCallback` is provided, calls it for every error (e.g. for external error reporting)
- [ ] Skips non-MCP contexts
- [ ] Note: `ErrorHandlingInterceptor` provides enhanced error reporting (stack traces, custom transformations, error callbacks) as opt-in behavior. Basic error normalization (converting all exceptions to `{ isError: true }` MCP responses) is always-on via the built-in `McpExceptionFilter` in CORE-010 — `ErrorHandlingInterceptor` is layered on top of that for advanced use cases.

### ToolInjectionInterceptor (FastMCP ToolInjectionMiddleware equivalent)
- [ ] `ToolInjectionInterceptor` implements `NestInterceptor`
- [ ] Dynamically injects additional tools into the registry for the duration of a request
- [ ] Options: `tools: McpToolDefinition[]`
- [ ] Injected tools are available during the request and removed after the request completes
- [ ] Triggers `sendToolListChanged()` notification on inject and removal
- [ ] Skips non-MCP contexts

### PromptToolInterceptor (FastMCP PromptToolMiddleware equivalent)
- [ ] `PromptToolInterceptor` implements `NestInterceptor`
- [ ] Exposes all registered prompts as callable tools (for LLM clients that only support the tools interface)
- [ ] Each prompt becomes a tool named `prompt_{promptName}`
- [ ] Tool arguments mirror the prompt's argument schema
- [ ] Tool result is the prompt's rendered messages serialized as text content
- [ ] Skips non-MCP contexts

### ResourceToolInterceptor (FastMCP ResourceToolMiddleware equivalent)
- [ ] `ResourceToolInterceptor` implements `NestInterceptor`
- [ ] Exposes all registered static resources as callable tools
- [ ] Each resource becomes a tool named `read_{resourceName}` (sanitized: spaces/special chars replaced with underscores)
- [ ] Tool takes no arguments (for static resources) or template params (for template resources)
- [ ] Tool result is the resource content as text content
- [ ] Skips non-MCP contexts

### OnInitializeGuard (FastMCP on_initialize hook equivalent)
- [ ] `OnInitializeGuard` implements `CanActivate`
- [ ] Hooks into MCP client initialization (connection handshake)
- [ ] Runs `canActivate`-style check on `McpServer`'s `oninitialized` event
- [ ] Can reject clients before handshake completes by returning `false` or throwing `McpError`
- [ ] Options: `validator: (clientInfo: ClientInfo) => boolean | Promise<boolean>`
- [ ] Skips non-MCP contexts

### General
- [ ] `getMcpIdentity(context)` helper used by all components (from CORE-006)
- [ ] All components exported from `@unique-ag/nestjs-mcp`

## BDD Scenarios

```gherkin
Feature: Built-in Pipeline Components
  The framework ships opt-in guards and interceptors that consumers
  register via standard NestJS DI to add logging, metrics, rate-limiting,
  caching, retries, response limiting, keepalive pings, error handling,
  dynamic tool injection, and cross-protocol exposure.

  Rule: Logging Interceptor

    Scenario: Successful tool call is logged with caller and duration
      Given the logging interceptor is registered globally
      And a tool "search_emails" is registered
      When user "user-123" calls "search_emails" and it completes in 150 ms
      Then a log entry records the call start with caller "user-123" and operation "tool:search_emails"
      And a log entry records the successful completion with duration 150 ms

    Scenario: Failed tool call is logged as an error
      Given the logging interceptor is registered globally
      And a tool "search_emails" is registered
      When a client calls "search_emails" and the handler throws "Graph API timeout"
      Then a log entry records the error for "tool:search_emails"
      And the error is still propagated to the caller

    Scenario: Non-MCP requests are ignored by the logging interceptor
      Given the logging interceptor is registered as a global interceptor
      When an HTTP request arrives at a REST controller
      Then no MCP-specific log entries are produced

  Rule: Metrics Interceptor

    Scenario: Successful tool call records a duration metric
      Given the metrics interceptor is registered globally
      When a client calls "search_emails" and it completes successfully in 200 ms
      Then an operation duration metric is recorded with value approximately 200 ms
      And the metric attributes include operation type "tool", name "search_emails", and status "success"

    Scenario: Failed tool call records an error metric
      Given the metrics interceptor is registered globally
      When a client calls "search_emails" and the handler throws an error
      Then an operation duration metric is recorded with status "error"
      And the error is still propagated to the caller

  Rule: Token Bucket Rate Limit Guard

    Scenario: Caller is blocked after exhausting their rate limit
      Given a token bucket rate limit guard allowing 5 calls per minute per user
      And user "user-123" has made 5 calls in the last minute
      When user "user-123" makes a 6th call
      Then the call is rejected with a rate limit error

    Scenario: Different users have independent rate limit buckets
      Given a token bucket rate limit guard allowing 5 calls per minute per user
      And user "user-123" has exhausted their limit
      When user "user-456" makes their first call
      Then the call is allowed

    Scenario: Unauthenticated callers are rate-limited by IP address
      Given a token bucket rate limit guard allowing 5 calls per minute
      And an unauthenticated request originates from IP "192.168.1.1"
      When the guard evaluates the request
      Then rate limiting is keyed to IP "192.168.1.1"

    Scenario: Rate limit resets after the time window elapses
      Given a token bucket rate limit guard allowing 5 calls per minute per user
      And user "user-123" has been rate-limited
      When 60 seconds elapse
      Then user "user-123" can make calls again

  Rule: Caching Interceptor

    Scenario: Repeated call with same arguments returns cached response
      Given the caching interceptor is registered on tool "get_weather" with a 60-second TTL
      And "get_weather" was called with location "Zurich" 10 seconds ago
      When a client calls "get_weather" with location "Zurich"
      Then the cached response is returned
      And the tool handler is not invoked

    Scenario: Cache entry expires after TTL
      Given the caching interceptor is registered on tool "get_weather" with a 5-second TTL
      And "get_weather" was called with location "Zurich" 10 seconds ago
      When a client calls "get_weather" with location "Zurich"
      Then the tool handler is invoked
      And the new result replaces the expired cache entry

    Scenario: Custom cache key includes caller identity
      Given the caching interceptor uses a key factory that includes the caller's user ID
      And user "user-A" called "get_settings" and the result was cached
      When user "user-B" calls "get_settings" with the same arguments
      Then the tool handler is invoked because the cache key differs by user

  Rule: Sliding Window Rate Limit Guard

    Scenario: Caller is blocked after exceeding the window limit
      Given a sliding window rate limit guard allowing 3 requests per 60 seconds
      And user "user-123" has made 3 calls within the current window
      When user "user-123" makes a 4th call
      Then the call is rejected with a rate limit error

    Scenario: Oldest call leaving the window frees capacity
      Given a sliding window rate limit guard allowing 3 requests per 60 seconds
      And user "user-123" made their first call 61 seconds ago and two more calls recently
      When user "user-123" makes a new call
      Then the call is allowed because the oldest call is outside the window

  Rule: Retry Interceptor

    Scenario: Transient failure is retried and succeeds
      Given the retry interceptor is configured with 3 max retries and 100 ms backoff
      And a tool handler that fails with a transient error on the first attempt but succeeds on the second
      When a client calls the tool
      Then the interceptor retries after approximately 100 ms
      And the successful second-attempt response is returned to the client

    Scenario: Business logic errors are not retried
      Given the retry interceptor is configured with 3 max retries
      And a tool handler that returns a business logic error "Invalid input: missing required field"
      When a client calls the tool
      Then the interceptor does not retry
      And the business logic error is returned immediately

    Scenario: All retries exhausted re-throws the original error
      Given the retry interceptor is configured with 2 max retries and exponential backoff
      And a tool handler that always fails with a transient error
      When a client calls the tool
      Then the interceptor retries twice with increasing delays
      And the original error is returned to the client after retries are exhausted

  Rule: Response Limiting Interceptor

    Scenario: Response within the character limit passes through unmodified
      Given the response limiting interceptor with a 50000-character limit
      And a tool handler returns 10000 characters of content
      When the interceptor processes the response
      Then the response passes through unchanged

    Scenario: Response exceeding the character limit is truncated
      Given the response limiting interceptor with a 1000-character limit
      And a tool handler returns 5000 characters of content
      When the interceptor processes the response
      Then the content is truncated to approximately 1000 characters
      And a notice "[Response truncated: exceeded 1000 character limit]" is appended

    Scenario: Structured output exceeding the limit drops structured content
      Given the response limiting interceptor with a 1000-character limit
      And a tool with a defined output schema returns 5000 characters of structured content
      When the interceptor processes the response
      Then the structured content is replaced with truncated text content and a truncation notice

  Rule: Ping / Keepalive Interceptor

    Scenario: Keepalive pings are sent during a long-running tool execution
      Given the ping interceptor with a 5-second interval is registered
      And a tool handler that takes 12 seconds to complete
      When a client calls the tool
      Then keepalive pings are sent at approximately 5 and 10 seconds
      And pings stop after the tool completes
      And the tool result is returned normally

  Rule: Structured Logging Interceptor

    Scenario: Tool call emits a structured JSON log entry
      Given the structured logging interceptor is registered globally
      When user "user-123" in session "sess-abc" calls "search_emails" and it completes in 150 ms
      Then a structured JSON log entry is emitted containing session ID "sess-abc", operation type "tool", operation name "search_emails", latency approximately 150 ms, and status "success"

  Rule: Timing Interceptor

    Scenario: Operation duration is logged
      Given the timing interceptor is registered globally
      When a resource read for "config://app" completes in 25 ms
      Then a log entry records "resource:config://app completed in 25ms"

  Rule: Detailed Timing Interceptor

    Scenario: Per-operation-type timing statistics are aggregated
      Given the detailed timing interceptor is registered globally
      And 3 tool calls have been made averaging 100 ms each
      And 2 resource reads have been made averaging 20 ms each
      When aggregated statistics are retrieved
      Then tools show average 100 ms with count 3
      And resources show average 20 ms with count 2

  Rule: Error Handling Interceptor

    Scenario: Error is normalized and reported via callback without stack trace
      Given the error handling interceptor is configured with stack traces disabled and an error callback
      And a tool handler throws "DB connection failed"
      When the interceptor catches the error
      Then the client receives an MCP error response without a stack trace
      And the error callback is invoked with the original error

  Rule: Tool Injection Interceptor

    Scenario: Dynamically injected tools are available only during the request
      Given the tool injection interceptor is configured with a tool "debug_info"
      When a client lists tools during a request handled by this interceptor
      Then "debug_info" appears in the tool list
      When the request completes
      Then "debug_info" is no longer available in the tool list

  Rule: Prompt-to-Tool Interceptor

    Scenario: Registered prompts are exposed as callable tools
      Given a prompt "draft-email" with arguments "to" and "subject" is registered
      And the prompt-to-tool interceptor is active
      When a client lists tools
      Then a tool named "prompt_draft-email" appears with matching arguments
      When a client calls "prompt_draft-email" with to "alice" and subject "Hello"
      Then the prompt is rendered and the result is returned as text content

  Rule: Resource-to-Tool Interceptor

    Scenario: Registered resources are exposed as callable tools
      Given a static resource "config://app/settings" named "App Settings" is registered
      And the resource-to-tool interceptor is active
      When a client lists tools
      Then a tool named "read_App_Settings" appears
      When a client calls "read_App_Settings"
      Then the resource content is returned as text content

  Rule: On-Initialize Guard

    Scenario: Blocked client is rejected during handshake
      Given the on-initialize guard rejects clients named "blocked-client"
      When a client named "blocked-client" attempts to connect
      Then the handshake is rejected
      And the client does not complete initialization

    Scenario: Accepted client completes handshake
      Given the on-initialize guard rejects clients named "blocked-client"
      When a client named "trusted-client" attempts to connect
      Then the handshake completes successfully
```

## Dependencies
- Depends on: INFRA-001 — package must exist
- Depends on: CORE-006 — getMcpIdentity helper
- Depends on: CORE-009 — switchToMcp() for accessing McpOperationContext
- Depends on: CORE-010 — pipeline runner executes these components
- Depends on: `@nestjs/cache-manager` — optional peer dependency for CachingInterceptor pluggable storage
- Blocks: CORE-012 — module registers these as opt-in global providers

## Technical Notes
- `LoggingInterceptor` implementation pattern (from design artifact):
  ```typescript
  intercept(context: ExecutionContext, next: CallHandler): Observable<any> {
    if (context.getType() !== 'mcp') return next.handle();
    const { name, type, identity } = context.switchToMcp().getMcpContext();
    const start = Date.now();
    this.logger.log(`-> ${type}:${name} by ${identity?.userId ?? 'anon'}`);
    return next.handle().pipe(
      tap(() => this.logger.log(`<- ${type}:${name} ${Date.now() - start}ms`)),
      catchError(err => { this.logger.error(`x ${type}:${name}`, err); throw err; }),
    );
  }
  ```
- `MetricsInterceptor` uses `@opentelemetry/api` (already a peer dep in the existing package). Create a histogram via `meter.createHistogram('mcp.operation.duration')`.
- `RateLimitGuard` uses an in-memory Map of token buckets keyed by `{userId}:{operationName}`. Not distributed — for distributed rate limiting, consumers should use Redis-backed alternatives.
- `CachingInterceptor` implementation notes:
  - Default storage: `Map<string, { value: any; expiresAt: number }>`
  - Pluggable storage interface: `CacheStore { get(key: string): Promise<any>; set(key: string, value: any, ttlMs: number): Promise<void>; }`
  - Compatible with `@nestjs/cache-manager` `Cache` interface
  - Default key: `${operationName}:${JSON.stringify(args)}` — note this excludes user identity, so user-specific responses will be incorrectly shared unless a custom `keyFactory` is provided
  - Stale entries are lazily evicted on next access (no background cleanup timer for simplicity)
- `SlidingWindowRateLimitGuard` implementation notes:
  - Maintains `Map<string, number[]>` — key is `{userId}:{operationName}`, value is array of timestamps
  - On each check: filter out timestamps outside window, count remaining, allow/deny
  - Memory bounded: old timestamps are pruned on each check
  - More precise than token bucket but slightly more memory-intensive (stores individual timestamps)
- `RetryInterceptor` implementation notes:
  - Uses RxJS `retry` operator with delay configuration
  - Transient error detection: check `error.status === 503`, `error.code === 'ECONNREFUSED'`, or `error instanceof McpError && error.retryable`
  - `ToolError` instances are never retried (they represent intentional business logic failures)
  - Backoff formula: `backoffMs * (backoffMultiplier ^ attemptIndex)`
- `ResponseLimitingInterceptor` implementation notes:
  - Inspects `result.content` array, sums character lengths of all text blocks
  - Truncation: iterates content blocks, truncating the block that crosses the limit
  - Appends a final text block with the truncation notice
  - When `outputSchema` is present on the tool definition, truncation could violate the schema — log a warning and drop structured content entirely, returning only the truncated text
- `PingInterceptor` implementation: wraps handler observable with `merge` that includes a `timer(intervalMs, intervalMs).pipe(tap(() => mcpServer.ping()))` stream. On handler completion (success or error), the ping interval is cleared via `takeUntil`. Uses `McpServer`'s built-in `ping()` method from `@modelcontextprotocol/sdk`.
- `StructuredLoggingInterceptor` extends `LoggingInterceptor`, overriding log output to JSON format. Extracts `requestId` from `McpContext._meta?.requestId` and `sessionId` from `McpContext.session?.id`. Options mirror `LoggingInterceptor` plus structured fields.
- `TimingInterceptor` is a lightweight variant of `LoggingInterceptor` that only logs duration, not entry/exit. Useful when full logging is too verbose.
- `DetailedTimingInterceptor` maintains an internal `Map<'tool' | 'resource' | 'prompt', { total: number, max: number, count: number }>` for aggregated stats. `getStats()` computes averages. Not thread-safe for distributed — local process only.
- `ErrorHandlingInterceptor` catches errors in `catchError` operator. Normalizes to `{ content: [{ type: 'text', text: error.message }], isError: true }`. When `includeTraceback` is true, appends stack trace. When `transformErrors` is true, attempts to map known error types to user-friendly messages.
- `ToolInjectionInterceptor` uses `McpRegistryService.register()` on request entry and `McpRegistryService.unregister()` on request completion (via `finalize` operator). Triggers `sendToolListChanged()` both times.
- `PromptToolInterceptor` reads `McpHandlerRegistry.getPrompts()` at activation time and registers synthetic tool entries named `prompt_{name}`. Tool handler delegates to the prompt handler and serializes the result as text content.
- `ResourceToolInterceptor` reads `McpHandlerRegistry.getStaticResources()` at activation time and registers synthetic tool entries named `read_{sanitizedName}`. Tool handler delegates to the resource `read()` method.
- `OnInitializeGuard` implements `CanActivate`. Hooks into `McpServer`'s `oninitialized` event callback. The `validator` function receives `ClientInfo` (client name, version, capabilities) and returns boolean. On rejection, throws `McpError` with `InvalidRequest` code.
- File locations:
  - `packages/nestjs-mcp/src/pipeline/logging.interceptor.ts`
  - `packages/nestjs-mcp/src/pipeline/metrics.interceptor.ts`
  - `packages/nestjs-mcp/src/pipeline/rate-limit.guard.ts`
  - `packages/nestjs-mcp/src/pipeline/caching.interceptor.ts`
  - `packages/nestjs-mcp/src/pipeline/sliding-window-rate-limit.guard.ts`
  - `packages/nestjs-mcp/src/pipeline/retry.interceptor.ts`
  - `packages/nestjs-mcp/src/pipeline/response-limiting.interceptor.ts`
  - `packages/nestjs-mcp/src/pipeline/ping.interceptor.ts`
  - `packages/nestjs-mcp/src/pipeline/structured-logging.interceptor.ts`
  - `packages/nestjs-mcp/src/pipeline/timing.interceptor.ts`
  - `packages/nestjs-mcp/src/pipeline/detailed-timing.interceptor.ts`
  - `packages/nestjs-mcp/src/pipeline/error-handling.interceptor.ts`
  - `packages/nestjs-mcp/src/pipeline/tool-injection.interceptor.ts`
  - `packages/nestjs-mcp/src/pipeline/prompt-tool.interceptor.ts`
  - `packages/nestjs-mcp/src/pipeline/resource-tool.interceptor.ts`
  - `packages/nestjs-mcp/src/pipeline/on-initialize.guard.ts`
