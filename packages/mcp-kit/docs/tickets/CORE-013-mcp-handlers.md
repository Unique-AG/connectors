# CORE-013: McpToolsHandler

## Summary
Implement `McpToolsHandler`, the handler service that registers SDK request handlers for tool-related MCP protocol operations (ListTools, CallTool). The handler retrieves the correct method from the registry, runs it through the pipeline (Zod -> Pipes -> Guards -> Interceptors -> Handler -> Serialization), injects `McpContext` at the `@Ctx()` position, and returns the properly formatted MCP response.

> **Note:** ResourcesHandler is specified in CORE-027; PromptsHandler in CORE-028. All three follow identical patterns — read CORE-027/028 for resource/prompt specifics.

## Background / Context
The tools handler service registers SDK request handlers for tool-related MCP protocol operations. It delegates to `McpPipelineRunner` for the full NestJS guard/interceptor/pipe pipeline and constructs `McpContext` for injection via `@Ctx()`.

The handler is orchestrated by `McpExecutorService` which registers it on the `McpServer` instance. It is REQUEST-scoped (tied to the HTTP request that established the MCP connection).

## Acceptance Criteria

### List-time authorization filtering (FastMCP parity)
- [ ] `McpToolsHandler.listTools()` evaluates per-tool guards before including a tool in the response — guarded tools that the current identity would fail are excluded
- [ ] A component that a guard would block MUST NOT appear in list responses (matches FastMCP behavior where authorization hides components)
- [ ] Guard evaluation for list requests builds a minimal `McpOperationContext` with the session identity and a "list" context type
- [ ] Guard that throws during list evaluation → component excluded from list, NO error propagated to client
- [ ] Guard that returns false during list evaluation → component excluded from list
- [ ] Components without guards always appear in list responses
- [ ] Uses `McpPipelineRunner.canList(handlerMeta, identity)` for list-time guard checks

### McpToolsHandler
- [ ] Registers `ListToolsRequestSchema` handler — returns only tools that pass list-time guard evaluation, with name, description, inputSchema (JSON Schema from Zod), outputSchema, annotations, title, _meta
- [ ] Registers `CallToolRequestSchema` handler — finds tool by name, runs pipeline, returns result
- [ ] Zod validation of input runs first; failure returns `McpError(InvalidParams)`
- [ ] Unknown tool name returns `McpError(MethodNotFound)`
- [ ] Injects `McpContext` at the `@Ctx()` parameter position
- [ ] Output auto-serialized via `formatToolResult()` (CORE-008)
- [ ] Errors normalized: `HttpException` / `McpError` / unknown -> `{ isError: true }` or protocol error

## BDD Scenarios

```gherkin
Feature: MCP Tools Handler
  The tools handler registers SDK request handlers for tool operations,
  routes calls through the pipeline, injects context, serializes output, and
  filters list responses based on authorization.

  Background:
    Given an MCP server is running with registered tools

  Rule: Tool call routing and execution

    Scenario: Tool call is routed to the correct handler
      Given tools "search_emails" and "send_email" are registered
      When a client calls "search_emails" with arguments query "test"
      Then the "search_emails" handler is invoked with query "test"
      And the response contains the handler's serialized return value

    Scenario: Unknown tool name returns an error
      Given tools "search_emails" and "send_email" are registered
      When a client calls "nonexistent_tool"
      Then the client receives a "method not found" error mentioning "nonexistent_tool"

    Scenario: Invalid arguments are rejected before the handler runs
      Given a tool "search_emails" that requires a string "query" parameter
      When a client calls "search_emails" with query as the number 123
      Then the client receives an InvalidParams error
      And the tool handler is not invoked

    Scenario: Tool handler return value is auto-serialized as text content
      Given a tool "count_items" that returns an object with count 5
      When a client calls "count_items"
      Then the response contains a text content block with the JSON representation of the result

    Scenario: MCP context is injected into the handler
      Given a tool "search_emails" whose handler accepts an MCP context parameter
      When a client calls "search_emails"
      Then the handler receives a context with operation type "tool" and operation name "search_emails"

    Scenario: Pipeline components are applied to tool calls
      Given a global logging interceptor and a per-tool admin guard are configured
      When a client calls a guarded tool
      Then the guard evaluates access before the handler runs
      And the interceptor wraps the handler execution

  Rule: List responses

    Scenario: All registered tools appear in the tool list
      Given 3 tools are registered with names, descriptions, and schemas
      When a client requests the tool list
      Then the response contains all 3 tools with their names, descriptions, and input schemas

  Rule: List-time authorization filtering

    Scenario: Guarded tool is hidden from unauthorized callers
      Given a tool "public_search" with no access restrictions
      And a tool "admin_delete" that requires the "admin" role
      And the current session belongs to a user without the "admin" role
      When a client requests the tool list
      Then "public_search" appears in the response
      And "admin_delete" does not appear in the response

    Scenario: Guarded tool is visible to authorized callers
      Given a tool "public_search" with no access restrictions
      And a tool "admin_delete" that requires the "admin" role
      And the current session belongs to a user with the "admin" role
      When a client requests the tool list
      Then both "public_search" and "admin_delete" appear in the response

    Scenario: Scope-restricted tool is hidden when caller lacks the required scope
      Given a tool "send_email" that requires the "mail.send" scope
      And the current session has only the "mail.read" scope
      When a client requests the tool list
      Then "send_email" does not appear in the response

    Scenario: Unauthenticated caller only sees unguarded tools
      Given a tool "public_info" with no access restrictions
      And a tool "protected_action" that requires authentication
      And the request is unauthenticated
      When a client requests the tool list
      Then "public_info" appears in the response
      And "protected_action" does not appear in the response

    Scenario: Guard error during list evaluation silently excludes the tool
      Given a tool "flaky_tool" whose guard throws an unexpected error during evaluation
      And other tools are registered normally
      When a client requests the tool list
      Then "flaky_tool" is excluded from the response
      And no error is returned to the client
      And other tools appear normally

    Scenario: Unguarded tools are always visible regardless of caller identity
      Given a tool "always_visible" with no access restrictions
      When any caller requests the tool list
      Then "always_visible" appears in the response
```

## Dependencies
- Depends on: INFRA-001 — package must exist
- Depends on: CORE-004 — @Ctx() parameter index for argument construction
- Depends on: CORE-005 — registry for looking up handlers
- Depends on: CORE-007 — McpContext construction
- Depends on: CORE-008 — output serialization (formatToolResult)
- Depends on: CORE-009 — McpExecutionContextHost needed to build list-time guard evaluation context
- Depends on: CORE-010 — pipeline runner for guard/interceptor/pipe execution; `canList()` method
- Depends on: CORE-012 — module wiring provides McpServer and config
- Blocks: CORE-027 — McpResourcesHandler (common handler infrastructure)
- Blocks: CORE-028 — McpPromptsHandler (common handler infrastructure)
- Blocks: SESS-001 — session store used during handler execution
- Blocks: SDK-003, SDK-004, SDK-005 — these extend handler behavior
- Blocks: CORE-017, CORE-023, CORE-024, CORE-025, CORE-026, AUTH-007

## Technical Notes
- The handler registers on `mcpServer.server.setRequestHandler()` (low-level SDK Server, not McpServer high-level API) to maintain full control over the request/response flow
- `McpContext` construction per call:
  ```typescript
  const ctx = McpContext.create({
    identity,
    server: mcpServer,
    operationType: 'tool',
    operationName: toolInfo.metadata.name,
    progressToken: request._meta?.progressToken,
  });
  ```
- Argument array construction:
  ```typescript
  const ctxIndex = registryEntry.ctxParamIndex;
  const args: unknown[] = [validatedInput];
  if (ctxIndex !== undefined) {
    while (args.length <= ctxIndex) args.push(undefined);
    args[ctxIndex] = ctx;
  }
  ```
- For ListTools, convert Zod schemas to JSON Schema using `z.toJSONSchema(schema, { io: 'input' })` (same as existing code)

### List-time authorization filtering implementation

**FastMCP parity**: FastMCP's authorization system hides components from list responses when auth checks fail — a user without `mail.send` scope never sees the `send_email` tool in `listTools`. Our implementation mirrors this behavior.

**Approach**: For each list request, iterate over registered tools and evaluate their guards via `McpPipelineRunner.canList()` before including them in the response.

```typescript
// McpToolsHandler.listTools() — with filtering
async listTools(): Promise<ListToolsResult> {
  const allTools = this.registry.getTools();
  const visibleTools: ToolInfo[] = [];

  for (const tool of allTools) {
    const canShow = await this.pipelineRunner.canList(tool, this.identity);
    if (canShow) {
      visibleTools.push(this.formatToolInfo(tool));
    }
  }

  return { tools: visibleTools };
}
```

**Edge cases**:
- Guard that accesses `ctx.identity` works because the list context includes the session identity
- Guard that accesses `ctx.operationName` works because the list context includes the handler name
- Guard that throws → component excluded, no error propagated (logged at debug level)
- Unauthenticated request (identity=null) → all guards that check identity will fail → guarded components hidden
- Performance: guard evaluation is per-component per-list-request. For servers with many guarded components, this adds latency to list requests. Future optimization: cache guard results per identity+component for the duration of a session
- File location: `packages/nestjs-mcp/src/services/handlers/mcp-tools.handler.ts`
- SDK APIs used:
  - `mcpServer.server.setRequestHandler(ListToolsRequestSchema, ...)`
  - `mcpServer.server.setRequestHandler(CallToolRequestSchema, ...)`
