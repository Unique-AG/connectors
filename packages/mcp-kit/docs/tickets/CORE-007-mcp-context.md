# CORE-007: McpContext class

## Summary
Implement the `McpContext` class that serves as the primary interface for tool, resource, and prompt handlers to interact with the MCP framework. It provides typed identity access, SDK-routed logging, progress reporting, LLM sampling, resource reading, elicitation, and an escape hatch to the raw `McpServer`.

## Background / Context
`McpContext` wraps all SDK interactions behind a clean, typed API that tool, resource, and prompt handlers access via `@Ctx()`. Critically, `McpContext` does NOT expose `httpRequest` — that is only available in the pipeline layer (`McpOperationContext` via `switchToMcp()`).

`McpContext` is constructed by the framework per invocation (not DI-managed directly). It receives the resolved `McpIdentity`, a reference to the `McpServer`, and metadata about the current operation.

## Acceptance Criteria
- [ ] `McpContext` class exported from `@unique-ag/nestjs-mcp`
- [ ] `identity` getter returns `McpIdentity` — throws `UnauthorizedError` with helpful message ("This MCP server requires authentication. No identity available.") if identity is null
- [ ] `isAuthenticated` boolean getter returns `true` when identity is non-null
- [ ] `log.debug(message)`, `log.info(message)`, `log.warn(message)`, `log.error(message)` — route to SDK `server.sendLoggingMessage()` with appropriate level
- [ ] `reportProgress(current, total, message?)` — calls SDK progress notification on the server
- [ ] `sample(prompt, options?)` — calls SDK `server.createMessage()` for LLM sampling, returns the response text
- [ ] `readResource(uri)` — reads a registered resource from within a tool handler
- [ ] `elicit<T>(schema, message)` — calls SDK `server.elicitInput()` for structured user input
- [ ] `operationType` readonly: `'tool' | 'resource' | 'resource-template' | 'prompt'`
- [ ] `operationName` readonly: the name of the current operation
- [ ] `server` readonly: escape hatch to the raw `McpServer` instance
- [ ] `sessionId` readonly: `string | null` — current MCP session ID (null for STDIO transport)
- [ ] `requestId` readonly: `string` — unique identifier for this request (generated per invocation)
- [ ] `clientId` readonly: `string | null` — OAuth client ID if authenticated, null otherwise
- [ ] `transport` readonly: `'streamable-http' | 'sse' | 'stdio'` — transport type for this connection
- [ ] `listResources()` method returns `Promise<ResourceRef[]>` — lists all registered resources visible to this client (respects session-level visibility overrides)
- [ ] `listPrompts()` method returns `Promise<PromptRef[]>` — lists all registered prompts visible to this client (respects session-level visibility overrides)
- [ ] `getPrompt(name, args?)` method returns `Promise<PromptResult>` — retrieves and renders a registered prompt by name
- [ ] Constructor is not public (framework-internal factory method)
- [ ] `ctx.requestMeta: Record<string, unknown> | null` — client-provided metadata from the MCP request's `_meta` field (available v2.13.1+). Returns null if absent.
- [ ] `ctx.clientInfo: { name: string; version: string } | null` — client name and version from MCP initialization handshake. Returns null if not yet initialized.
- [ ] Both `requestMeta` and `clientInfo` are available on tools, resources, and prompts context

## BDD Scenarios

```gherkin
Feature: McpContext provides handler access to framework capabilities

  Rule: Identity access reflects authentication state

    Scenario: Accessing identity on an authenticated context returns the identity
      Given a tool is called by an authenticated user "alice@example.com"
      When the handler accesses the context identity
      Then the identity contains the authenticated user's details
      And isAuthenticated is true

    Scenario: Accessing identity on an unauthenticated context throws an error
      Given a tool is called without authentication
      When the handler accesses the context identity
      Then an error is thrown indicating authentication is required
      And isAuthenticated is false

  Rule: Logging routes messages to the connected MCP client

    Scenario Outline: Log messages are sent at the correct level
      Given a tool handler with an active MCP context
      When the handler logs a "<level>" message "something happened"
      Then the connected MCP client receives a log message at level "<level>"

      Examples:
        | level |
        | debug |
        | info  |
        | warn  |
        | error |

  Rule: Progress can be reported to the client during long operations

    Scenario: Progress notification is sent to the client
      Given a tool handler processing a batch of 100 items
      When the handler reports progress at 50 of 100 with message "Processing..."
      Then the connected MCP client receives a progress update showing 50 of 100

  Rule: LLM sampling requires client support

    Scenario: Sampling succeeds when the client supports it
      Given a tool handler with an MCP client that supports sampling
      When the handler requests an LLM completion with prompt "Summarize this"
      Then the client processes the sampling request
      And the response text is returned to the handler

    Scenario: Sampling fails when the client does not support it
      Given a tool handler with an MCP client that does not support sampling
      When the handler requests an LLM completion
      Then an error is thrown indicating sampling is not supported

  Rule: Elicitation collects structured input from the user

    Scenario: Elicitation presents a schema and returns validated input
      Given a tool handler that needs user confirmation
      When the handler elicits input with a boolean "confirm" field and message "Please confirm"
      Then the connected client prompts the user
      And the validated response is returned to the handler

  Rule: Resources can be read from within tool handlers

    Scenario: Reading a registered resource returns its content
      Given a registered resource at "config://app/settings"
      When a tool handler reads resource "config://app/settings" via the context
      Then the resource content is returned

    Scenario: Reading an unregistered resource throws an error
      Given no resource registered at "unknown://missing"
      When a tool handler reads resource "unknown://missing" via the context
      Then an error is thrown mentioning "unknown://missing"

  Rule: Operation metadata identifies the current invocation

    Scenario: Context reports the current operation type and name
      Given a tool named "search_emails" is invoked
      When the handler inspects the context
      Then the operation type is "tool"
      And the operation name is "search_emails"

    Scenario: Each invocation gets a unique request ID
      Given two consecutive calls to the same tool within one session
      When each handler inspects its context request ID
      Then the two request IDs are different

  Rule: Session and transport information is available

    Scenario Outline: Session ID reflects the transport type
      Given a tool is called over "<transport>" transport
      When the handler inspects the context session ID
      Then the session ID is <session_id>

      Examples:
        | transport       | session_id       |
        | streamable-http | a non-null value |
        | stdio           | null             |

    Scenario: Transport type is reported correctly
      Given a tool is called over streamable-http transport
      When the handler inspects the context transport
      Then it reports "streamable-http"

  Rule: Client identity reflects OAuth authentication state

    Scenario: Client ID is available when authenticated via OAuth
      Given a tool is called by a client authenticated with client_id "my-app"
      When the handler inspects the context client ID
      Then it returns "my-app"

    Scenario: Client ID is null when unauthenticated
      Given a tool is called without OAuth authentication
      When the handler inspects the context client ID
      Then it returns null

  Rule: Handler can list and retrieve registered prompts and resources

    Scenario: Listing resources respects session visibility
      Given 3 registered resources, 1 hidden from the current session
      When a tool handler lists resources via the context
      Then 2 resources are returned

    Scenario: Listing prompts returns all visible prompts
      Given 2 registered prompts visible to the current session
      When a tool handler lists prompts via the context
      Then 2 prompts are returned with their names and descriptions

    Scenario: Retrieving a registered prompt renders it with arguments
      Given a registered prompt "greeting" that accepts a "name" argument
      When a tool handler calls getPrompt with name "greeting" and args name "Alice"
      Then the rendered prompt messages contain "Alice"

    Scenario: Retrieving an unknown prompt throws an error
      Given no prompt registered with name "nonexistent"
      When a tool handler calls getPrompt with name "nonexistent"
      Then an error is thrown mentioning "nonexistent"

  Rule: Client-provided metadata is accessible

    Scenario: Request metadata from the client is available
      Given an MCP client sends a tool call with metadata containing trace_id "abc"
      When the handler inspects the context request metadata
      Then the trace_id is "abc"

    Scenario: Client info is available after the initialization handshake
      Given an MCP client named "my-client" version "2.0.0" completes the handshake
      When a tool handler inspects the context client info
      Then the client name is "my-client"
      And the client version is "2.0.0"

  Rule: The raw MCP server is accessible as an escape hatch

    Scenario: Advanced SDK methods can be called via the server reference
      Given a tool handler with an active MCP context
      When the handler accesses the server property
      Then it receives the underlying McpServer instance
```

## Dependencies
- Depends on: INFRA-001 — package must exist
- Depends on: CORE-006 — McpIdentity interface
- Depends on: CORE-010 — pipeline runner (McpContext is created within the pipeline)
- Blocks: CORE-013 — handlers construct McpContext and inject via @Ctx()
- Blocks: SDK-001 — ctx.elicit() implementation
- Blocks: SDK-002 — ctx.sample() implementation

## Interface Contract
Consumed by CORE-013 (handlers inject via @Ctx()), SDK-001, SDK-002:
```typescript
export interface ResourceRef {
  uri: string;
  name: string;
  description?: string;
  mimeType?: string;
}

export interface PromptRef {
  name: string;
  description?: string;
  arguments?: Array<{ name: string; description?: string; required?: boolean }>;
}

export interface PromptResult {
  description?: string;
  messages: Array<{ role: 'user' | 'assistant'; content: { type: string; text: string } }>;
}

export class McpContext {
  private constructor(/* ... */);
  static create(params: McpContextParams): McpContext;

  get identity(): McpIdentity;                    // throws if null
  get isAuthenticated(): boolean;
  readonly log: { debug(msg: string): void; info(msg: string): void; warn(msg: string): void; error(msg: string): void };
  reportProgress(current: number, total: number, message?: string): Promise<void>;
  sample(prompt: string, options?: SamplingOptions): Promise<string>;
  readResource(uri: string): Promise<ResourceContent[]>;
  elicit<T extends z.ZodObject<any>>(schema: T, message: string): Promise<z.infer<T>>;
  listResources(): Promise<ResourceRef[]>;
  listPrompts(): Promise<PromptRef[]>;
  getPrompt(name: string, args?: Record<string, string>): Promise<PromptResult>;
  readonly operationType: 'tool' | 'resource' | 'resource-template' | 'prompt';
  readonly operationName: string;
  readonly server: McpServer;
  readonly sessionId: string | null;
  readonly requestId: string;
  readonly clientId: string | null;
  readonly transport: 'streamable-http' | 'sse' | 'stdio';
  readonly requestMeta: Record<string, unknown> | null; // from request._meta
  readonly clientInfo: { name: string; version: string } | null; // from init handshake
}
```

## Technical Notes
- `McpContext` is NOT request-scoped via DI. It is constructed imperatively by the handler:
  ```typescript
  const ctx = McpContext.create({
    identity,
    server: mcpServer,
    operationType: 'tool',
    operationName: toolName,
    progressToken: request._meta?.progressToken,
  });
  ```
- Use a private constructor + static `create()` factory to prevent external instantiation
- `reportProgress` uses the SDK's `server.server.sendNotification` with `notifications/progress` method, passing `progressToken` from the original request's `_meta`
- `sample` wraps `server.server.createMessage()` — needs to handle the case where the client doesn't support sampling (check capabilities)
- `elicit` wraps `server.elicitInput()` from SDK v1.25.2 — schema is converted to JSON Schema via `z.toJSONSchema()`
- `readResource` calls back into the registered resource handlers — implementation may delegate to the registry
- `log` methods use `server.server.sendLoggingMessage({ level, logger, data })` where logger defaults to the operation name
- `sessionId` is extracted from the transport-level session (Streamable HTTP / SSE session ID). For STDIO, it is always `null`
- `requestId` is a UUID v4 generated per invocation by the framework when constructing McpContext
- `clientId` is extracted from the resolved `McpIdentity.clientId` if available, or `null`
- `transport` is determined from the active transport adapter and passed into `McpContextParams`
- `requestMeta` is extracted from the MCP request's `_meta` field. Returns `null` if the request has no `_meta`. Available in SDK v2.13.1+
- `clientInfo` is extracted from the MCP initialization handshake (`ClientCapabilities.clientInfo`). Stored at the session level and passed into `McpContextParams`. Returns `null` if the handshake has not completed or the client did not declare info
- `listResources()` delegates to `McpHandlerRegistry.getResources()` filtered by session-level visibility overrides (SDK-007). Returns `ResourceRef[]` with uri, name, description, mimeType
- `listPrompts()` delegates to `McpHandlerRegistry.getPrompts()` filtered by session-level visibility overrides (SDK-007). Returns `PromptRef[]` with name, description, arguments
- `getPrompt()` delegates to the registered prompt handler via registry lookup — throws `McpError(InvalidParams)` if prompt name not found
- **FastMCP parity:** `sessionId`, `requestId`, `clientId`, `transport`, `listResources()`, `listPrompts()`, `getPrompt()` map directly to FastMCP Context properties and methods. `get_state`/`set_state` are handled separately in SDK-006
- **Session visibility note**: Session visibility methods (`ctx.enableComponents()`, `ctx.disableComponents()`) are defined in SDK-007. In this ticket, stub the interface with `// defined in SDK-007` comments. Do not implement the visibility logic here
- File location: `packages/nestjs-mcp/src/context/mcp-context.ts`
