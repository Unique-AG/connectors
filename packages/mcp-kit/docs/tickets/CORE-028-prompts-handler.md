# CORE-028: McpPromptsHandler

## Summary
Implement `McpPromptsHandler`, the handler service that registers SDK request handlers for prompt-related MCP protocol operations (ListPrompts, GetPrompt). The handler retrieves the correct method from the registry, runs it through the pipeline, injects `McpContext` at the `@Ctx()` position, and returns the properly formatted MCP response.

> **Note:** This ticket follows the same structural patterns as CORE-013 (McpToolsHandler). Read CORE-013 for common handler infrastructure details.

## Background / Context
The prompts handler service registers SDK request handlers for prompt-related MCP protocol operations. It delegates to `McpPipelineRunner` for the full NestJS guard/interceptor/pipe pipeline and constructs `McpContext` for injection via `@Ctx()`.

The handler is orchestrated by `McpExecutorService` which registers it on the `McpServer` instance. It is REQUEST-scoped (tied to the HTTP request that established the MCP connection).

Prompts expose their argument metadata (name, description, required) in list responses by converting Zod schema shape entries to MCP prompt argument format.

## Acceptance Criteria

### List-time authorization filtering (FastMCP parity)
- [ ] `McpPromptsHandler.listPrompts()` evaluates per-prompt guards before including a prompt in the response — guarded prompts that the current identity would fail are excluded
- [ ] A component that a guard would block MUST NOT appear in list responses
- [ ] Guard that throws during list evaluation → component excluded from list, NO error propagated to client
- [ ] Guard that returns false during list evaluation → component excluded from list
- [ ] Components without guards always appear in list responses
- [ ] Uses `McpPipelineRunner.canList(handlerMeta, identity)` for list-time guard checks

### McpPromptsHandler
- [ ] Registers `ListPromptsRequestSchema` handler — returns all prompts that pass list-time guard evaluation, with name, description, arguments (converted from Zod schema)
- [ ] Registers `GetPromptRequestSchema` handler — finds prompt by name, validates params, runs full pipeline, returns result
- [ ] Prompt parameters converted from Zod to MCP format: `{ name, description, required }` tuples
- [ ] Zod validation of prompt arguments runs first; failure returns `McpError(InvalidParams)`
- [ ] Unknown prompt name returns `McpError(MethodNotFound)` mentioning the prompt name
- [ ] Injects `McpContext` at the `@Ctx()` parameter position
- [ ] Prompt handler return value is expected to be `GetPromptResult` (messages array) — no auto-serialization like tools

## BDD Scenarios

```gherkin
Feature: MCP Prompts Handler
  The prompts handler registers SDK request handlers for prompt operations,
  routes get-prompt calls through the pipeline, injects context, converts
  Zod schemas to prompt argument metadata, and filters list responses based
  on authorization.

  Background:
    Given an MCP server is running with registered prompts

  Rule: Prompt get routing and execution

    Scenario: Prompt get is routed to the correct handler
      Given prompts "summarize" and "translate" are registered
      When a client requests prompt "summarize" with arguments topic "AI safety"
      Then the "summarize" handler is invoked with topic "AI safety"
      And the response contains the handler's prompt messages

    Scenario: Unknown prompt name returns an error
      Given prompts "summarize" and "translate" are registered
      When a client requests prompt "nonexistent_prompt"
      Then the client receives a "method not found" error mentioning "nonexistent_prompt"

    Scenario: Invalid prompt arguments are rejected before the handler runs
      Given a prompt "translate" that requires a string "text" parameter and a string "language" parameter
      When a client requests prompt "translate" with text as the number 123
      Then the client receives an InvalidParams error
      And the prompt handler is not invoked

    Scenario: Prompt with no arguments can be invoked with empty input
      Given a prompt "greeting" with no arguments
      When a client requests prompt "greeting" with no arguments
      Then the prompt handler is invoked
      And the response contains the rendered prompt messages

    Scenario: MCP context is injected into the prompt handler
      Given a prompt "summarize" whose handler accepts an MCP context parameter
      When a client requests prompt "summarize"
      Then the handler receives a context with operation type "prompt" and operation name "summarize"

    Scenario: Pipeline components are applied to prompt gets
      Given a global logging interceptor and a per-prompt admin guard are configured
      When a client requests a guarded prompt
      Then the guard evaluates access before the handler runs
      And the interceptor wraps the handler execution

  Rule: List responses

    Scenario: All registered prompts appear in the prompt list
      Given 3 prompts are registered with names, descriptions, and argument schemas
      When a client requests the prompt list
      Then the response contains all 3 prompts with their names and descriptions

    Scenario: Prompt arguments are described in the list response
      Given a prompt with a required "recipient" argument described as "Email address"
      And an optional "cc" argument described as "CC recipients"
      When a client requests the prompt list
      Then the prompt entry includes an argument named "recipient" marked as required with description "Email address"
      And the prompt entry includes an argument named "cc" marked as not required with description "CC recipients"

  Rule: List-time authorization filtering

    Scenario: Guarded prompt is hidden from unauthorized callers
      Given a prompt "admin_report" that requires the "admin" role
      And a prompt "public_greeting" with no access restrictions
      And the current session does not have the "admin" role
      When a client requests the prompt list
      Then "public_greeting" appears in the response
      And "admin_report" does not appear in the response

    Scenario: Guarded prompt is visible to authorized callers
      Given a prompt "admin_report" that requires the "admin" role
      And the current session has the "admin" role
      When a client requests the prompt list
      Then "admin_report" appears in the response

    Scenario: Guard error during list evaluation silently excludes the prompt
      Given a prompt "flaky_prompt" whose guard throws an unexpected error during evaluation
      And other prompts are registered normally
      When a client requests the prompt list
      Then "flaky_prompt" is excluded from the response
      And no error is returned to the client
      And other prompts appear normally

    Scenario: Unguarded prompts are always visible regardless of caller identity
      Given a prompt "always_visible" with no access restrictions
      When any caller requests the prompt list
      Then "always_visible" appears in the response

    Scenario: Unauthenticated caller only sees unguarded prompts
      Given a prompt "public_greeting" with no access restrictions
      And a prompt "protected_report" that requires authentication
      And the request is unauthenticated
      When a client requests the prompt list
      Then "public_greeting" appears in the response
      And "protected_report" does not appear in the response
```

## Dependencies
- Depends on: CORE-003 — @Prompt() decorator metadata
- Depends on: CORE-005 — registry for looking up handlers
- Depends on: CORE-007 — McpContext construction
- Depends on: CORE-008 — output serialization
- Depends on: CORE-009 — McpExecutionContextHost needed to build list-time guard evaluation context
- Depends on: CORE-010 — pipeline runner for guard/interceptor/pipe execution; `canList()` method
- Depends on: CORE-012 — module wiring provides McpServer and config
- Depends on: CORE-013 — common handler infrastructure patterns
- Blocks: none

## Technical Notes
- The handler registers on `mcpServer.server.setRequestHandler()` (low-level SDK Server, not McpServer high-level API) to maintain full control over the request/response flow
- For ListPrompts, convert Zod object keys to MCP prompt argument format:
  ```typescript
  const shape = schema.shape;
  const args = Object.entries(shape).map(([name, zodType]) => ({
    name,
    description: zodType.description,
    required: !zodType.isOptional(),
  }));
  ```
- Prompt handlers return `GetPromptResult` directly (an object with `messages` array). Unlike tools, there is no `formatToolResult()` auto-serialization step — the prompt handler is expected to return the correct structure.
- `McpContext` for prompt operations uses `operationType: 'prompt'`
- File location: `packages/nestjs-mcp/src/services/handlers/mcp-prompts.handler.ts`
- SDK APIs used:
  - `mcpServer.server.setRequestHandler(ListPromptsRequestSchema, ...)`
  - `mcpServer.server.setRequestHandler(GetPromptRequestSchema, ...)`
