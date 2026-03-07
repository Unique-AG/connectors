# SDK-001: ctx.elicit() -- structured user input

## Summary
Expose the MCP SDK's `server.elicitInput()` method through `McpContext.elicit(schema, message)`, enabling tools to collect structured user input during execution. The framework handles Zod-to-JSON-Schema conversion, ElicitationResult unwrapping (accept/decline/cancel), and error mapping.

## Background / Context
The MCP SDK v1.25.2 supports elicitation — a mechanism for servers to request structured input from users during tool execution. The SDK's `server.elicitInput()` sends an elicitation request to the client, which presents a form based on a JSON Schema and returns the user's response. This is useful for confirmation dialogs, multi-step wizards, and collecting additional parameters that depend on initial tool results.

Currently, our framework does not expose this capability. Tool authors would need to access `ctx.server` (escape hatch) and manually handle JSON Schema conversion and result unwrapping.

## Acceptance Criteria
- [ ] `McpContext.elicit<T extends z.ZodObject>(schema: T, message: string): Promise<z.infer<T>>` is available to tools via `@Ctx()`
- [ ] Zod schema is auto-converted to JSON Schema using `toJSONSchema()` (from zod v4)
- [ ] If the user accepts, the validated data is returned (type-safe via Zod inference)
- [ ] If the user declines, `McpElicitationDeclinedError` is thrown
- [ ] If the user cancels, `McpElicitationCancelledError` is thrown
- [ ] Both error classes extend a base `McpElicitationError` for catch-all handling
- [ ] The response data is validated against the Zod schema before returning (defense in depth)
- [ ] Elicitation works with Streamable HTTP transport (stateful sessions)
- [ ] Meaningful error thrown if elicitation is attempted on a transport/client that doesn't support it

## BDD Scenarios

```gherkin
Feature: Structured user input via elicitation
  Tools can collect structured input from users during execution
  using a schema-defined form that the MCP client presents.

  Background:
    Given an MCP server with the elicitation capability enabled
    And a connected MCP client that supports elicitation

  Rule: Accepted elicitation returns validated, typed data

    Scenario: User accepts a confirmation form with structured fields
      Given a tool "delete_workspace" that requests confirmation with fields "confirm" (boolean) and "reason" (text)
      When an MCP client calls "delete_workspace"
      Then the client receives a form with a boolean field "confirm" and a text field "reason"
      When the user accepts with confirm: true and reason: "cleanup"
      Then the tool receives { confirm: true, reason: "cleanup" } as typed data

    Scenario: Schema constraints are enforced on accepted responses
      Given a tool "set_count" that requests a numeric "count" field with minimum value 1
      When an MCP client calls "set_count"
      And the user accepts with count: -5
      Then the tool receives a validation error indicating the value is below the minimum

  Rule: Declined and cancelled elicitations produce distinct errors

    Scenario: User declines the elicitation form
      Given a tool "confirm_action" that requests user confirmation
      When an MCP client calls "confirm_action"
      And the user declines the form
      Then the tool receives an elicitation-declined error

    Scenario: User cancels the elicitation form
      Given a tool "confirm_action" that requests user confirmation
      When an MCP client calls "confirm_action"
      And the user cancels the form
      Then the tool receives an elicitation-cancelled error

  Rule: Elicitation requires a capable, stateful client

    Scenario: Client does not support elicitation
      Given a connected MCP client that does not support elicitation
      And a tool "interactive_tool" that requests user input
      When an MCP client calls "interactive_tool"
      Then the tool receives an error indicating the client does not support elicitation

    Scenario: Elicitation attempted on a stateless connection
      Given a stateless Streamable HTTP connection with no session
      And a tool "interactive_tool" that requests user input
      When an MCP client calls "interactive_tool"
      Then the tool receives an error indicating elicitation requires a stateful session

  Rule: Abort signals cancel in-flight elicitations

    Scenario: Client disconnects before responding to elicitation
      Given a tool "confirm_action" that requests user confirmation
      When an MCP client calls "confirm_action"
      And the client disconnects before responding to the form
      Then the tool receives an abort error
```

## FastMCP Parity
FastMCP (Python) exposes elicitation via `ctx.elicit()` with a Pydantic model for structured input collection. Our implementation mirrors this with Zod schemas instead of Pydantic. FastMCP also supports `ElicitationResult` with accept/decline/cancel actions — we wrap these into typed errors for a more idiomatic TypeScript DX.

## Dependencies
- **Depends on:** CORE-007 (McpContext class) — `elicit()` is a method on McpContext
- **Blocks:** none

## Technical Notes
- SDK API: `server.elicitInput({ message, requestedSchema }, { signal? })` returns `Promise<ElicitationResult>`
- `ElicitationResult` has shape: `{ action: 'accept' | 'decline' | 'cancel', content?: Record<string, unknown> }`
- Implementation in `McpContext`:
  ```typescript
  async elicit<T extends z.ZodObject<any>>(schema: T, message: string): Promise<z.infer<T>> {
    const jsonSchema = toJSONSchema(schema);
    const result = await this.server.elicitInput(
      { message, requestedSchema: jsonSchema },
      { signal: this.abortSignal }
    );
    if (result.action === 'decline') throw new McpElicitationDeclinedError(message);
    if (result.action === 'cancel') throw new McpElicitationCancelledError(message);
    // Validate response against schema for safety
    return schema.parse(result.content);
  }
  ```
- Error classes should live in `packages/nestjs-mcp/src/errors/`
- The `server` capability for elicitation must be enabled — check if SDK auto-advertises or if we need to declare it in server capabilities
