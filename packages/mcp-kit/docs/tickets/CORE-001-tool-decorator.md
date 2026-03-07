# CORE-001: @Tool() decorator

## Summary
Implement the `@Tool()` method decorator that marks NestJS service methods as MCP tools. The decorator auto-derives the tool name from the method name (camelCase to snake_case), supports Zod schema parameters in both full and shorthand forms, and propagates `title` to `annotations.title`.

## Background / Context
The `@Tool()` decorator marks NestJS service methods as MCP tools with:
1. Automatic name derivation (method name `searchEmails` becomes `search_emails`)
2. Parameter shorthand: `{ a: z.number(), b: z.number() }` auto-wraps to `z.object({ a: z.number(), b: z.number() })`
3. `title` auto-propagates to `annotations.title` (so you don't need to set both)
4. `meta` field (renamed from `_meta` for ergonomics)
The decorator stores metadata under a `MCP_TOOL_METADATA` symbol key (not string) using `Reflect.defineMetadata` on the method descriptor, rather than using NestJS `SetMetadata` which stores on the method function itself.

## Acceptance Criteria
- [ ] `@Tool()` is exported from `@unique-ag/nestjs-mcp`
- [ ] Name auto-derived from method name using camelCase-to-snake_case conversion
- [ ] Name can be overridden via `name` option
- [ ] `description` is required in options
- [ ] `parameters` accepts a `z.ZodObject` directly
- [ ] `parameters` accepts `Record<string, z.ZodType>` shorthand — auto-wrapped in `z.object()`
- [ ] `parameters` defaults to `z.object({})` when omitted
- [ ] `outputSchema` accepts optional `z.ZodObject`
- [ ] `title` option auto-propagates to `annotations.title` if `annotations.title` is not explicitly set
- [ ] `annotations` accepts a partial — only non-default values needed
- [ ] `meta` is stored and later emitted as `_meta` on the wire
- [ ] `timeout` option (optional `number`, milliseconds) stored in metadata — when exceeded, pipeline runner throws `McpError(RequestTimeout)` and returns `{ isError: true }`
- [ ] `mask` option (optional `boolean`) stored in metadata — when `true`, internal error details are replaced with generic "Internal server error" message in client responses. Per-tool `mask` overrides module-level `maskErrorDetails` (CORE-012)
- [ ] `icons` option stores array of `McpIcon` objects and includes them in `listTools` responses (v2.13.0+ parity)
- [ ] `version` option stores a string or number version identifier in metadata (v3.0.0+ parity)
- [ ] When two tools register the same name with different `version` values, the registry keeps the highest version (interacts with `onDuplicate` from CORE-012)
- [ ] Metadata stored under `MCP_TOOL_METADATA` symbol (exported from constants)
- [ ] `ToolOptions` and `ToolMetadata` TypeScript interfaces exported

## BDD Scenarios

```gherkin
Feature: @Tool() decorator for MCP tool registration

  Rule: Tool name is derived from the method name or explicitly set

    Scenario: Name auto-derived from method name using snake_case
      Given a service method named "searchEmails" decorated as a tool with description "Search"
      When an MCP client lists available tools
      Then a tool named "search_emails" appears in the list

    Scenario: Explicit name overrides auto-derived name
      Given a service method named "searchEmails" decorated as a tool with name "find_mail"
      When an MCP client lists available tools
      Then a tool named "find_mail" appears in the list
      And no tool named "search_emails" appears

  Rule: Tool parameters are validated against the declared schema

    Scenario: Shorthand parameter record is treated as a schema
      Given a tool "add_numbers" that declares parameters "a" (integer) and "b" (integer)
      When an MCP client calls "add_numbers" with a=3 and b=5
      Then the tool receives validated integers 3 and 5

    Scenario: Invalid parameters are rejected
      Given a tool "add_numbers" that declares parameters "a" (integer) and "b" (integer)
      When an MCP client calls "add_numbers" with a="hello" and b=5
      Then the call is rejected with a parameter validation error

    Scenario: Tool with no declared parameters accepts empty input
      Given a tool "get_status" with no declared parameters
      When an MCP client calls "get_status" with no arguments
      Then the tool executes successfully

  Rule: Title propagates to annotations unless explicitly overridden

    Scenario: Title appears as the annotation title
      Given a tool with title "Search Emails"
      When an MCP client lists available tools
      Then the tool's annotation title is "Search Emails"

    Scenario: Explicit annotation title takes precedence over title
      Given a tool with title "Search Emails" and an explicit annotation title "Custom Title"
      When an MCP client lists available tools
      Then the tool's annotation title is "Custom Title"

  Rule: Output schema enables structured content responses

    Scenario: Tool with output schema returns structured content
      Given a tool "count_items" with an output schema requiring a "count" integer
      When the tool returns a result with count 5
      Then the MCP response includes structured content with count 5
      And a text representation of the result is also included

    Scenario: Tool result that violates output schema produces an error
      Given a tool "count_items" with an output schema requiring a "count" integer
      When the tool returns a result where count is "not a number"
      Then the MCP response indicates an internal error

  Rule: Timeout aborts long-running tools

    Scenario: Tool exceeding its timeout is aborted
      Given a tool "slow_search" with a 5000ms timeout
      When an MCP client calls "slow_search" and the handler takes 10 seconds
      Then the call is aborted with a timeout error
      And the MCP response indicates an error

    Scenario: Tool completing within its timeout returns normally
      Given a tool "fast_search" with a 5000ms timeout
      When an MCP client calls "fast_search" and the handler completes in 100ms
      Then the tool result is returned successfully

  Rule: Error masking hides internal details from clients

    Scenario: Masked tool replaces internal error with generic message
      Given a tool "sensitive_op" with error masking enabled
      When the tool throws an error "DB connection failed at 10.0.0.5"
      Then the MCP client receives "Internal server error"
      And the original error details are not exposed

    Scenario: Unmasked tool forwards the original error message
      Given a tool "debug_op" with error masking disabled
      When the tool throws an error "Something broke"
      Then the MCP client receives "Something broke"

  Rule: Icons and version metadata appear in tool listings

    Scenario: Tool icons are included in the tools list
      Given a tool with an icon at "https://example.com/search.svg" of type "image/svg+xml"
      When an MCP client lists available tools
      Then the tool entry includes that icon URI and MIME type

    Scenario: Higher-versioned tool wins on duplicate name
      Given two services each register a tool named "search"
      And service A registers version 1 and service B registers version 2
      When the application starts and duplicate resolution is not set to error
      Then only the version 2 tool is registered

  Rule: Custom metadata is forwarded on the wire

    Scenario: Meta field is included in tool responses
      Given a tool with meta containing key "unique.app/icon" set to "search"
      When an MCP client calls the tool
      Then the response metadata includes "unique.app/icon" with value "search"

  Rule: Description is mandatory

    Scenario: Omitting description causes a compile-time error
      Given a developer decorates a method as a tool without providing a description
      When the project is compiled
      Then a type error is raised for the missing "description" property
```

## Dependencies
- Depends on: INFRA-001 — package must exist
- Blocks: CORE-005, AUTH-001, SDK-003, CORE-014, CORE-016

## Interface Contract
Consumed by CORE-005 (registry), CORE-013 (handlers), and SDK-003 (Tasks API):
```typescript
export const MCP_TOOL_METADATA = Symbol('MCP_TOOL_METADATA');

export interface ToolOptions {
  name?: string;
  title?: string;
  description: string;
  parameters?: z.ZodObject<any> | Record<string, z.ZodType>;
  outputSchema?: z.ZodObject<any>;
  annotations?: Partial<ToolAnnotations>;
  meta?: Record<string, unknown>;
  timeout?: number;                        // per-tool timeout in ms (FastMCP parity: `timeout` seconds)
  mask?: boolean;                          // mask internal error details (FastMCP parity: `mask_error_details`)
  icons?: McpIcon[];                      // visual representations for client display (v2.13.0+ parity)
  version?: string | number;               // version identifier; highest version wins on duplicate name (v3.0.0+ parity)
}

export interface ToolMetadata {
  name: string;                          // resolved (auto-derived or explicit)
  title?: string;
  description: string;
  parameters: z.ZodObject<any>;          // always resolved to ZodObject
  outputSchema?: z.ZodObject<any>;
  annotations: ToolAnnotations;          // merged (title propagated)
  meta?: Record<string, unknown>;
  icons?: McpIcon[];                     // visual representations for client display
  version?: string | number;             // version identifier for multi-version support
  timeout?: number;                      // per-tool timeout in ms
  mask?: boolean;                        // per-tool error masking override
  methodName: string;
}
```

## Technical Notes
- Name derivation helper: `camelToSnakeCase(name: string): string` — handles consecutive capitals (e.g., `parseHTMLContent` -> `parse_html_content`)
- Use `Reflect.defineMetadata(MCP_TOOL_METADATA, resolvedMetadata, descriptor.value)` for metadata storage
- The `MCP_TOOL_METADATA` constant should be a `Symbol('MCP_TOOL_METADATA')` (not a string) to avoid collisions
- For per-tool guards and interceptors, use standard NestJS `@UseGuards()` and `@UseInterceptors()` decorators directly on the method — `ExternalContextCreator` (CORE-010) picks them up automatically
- Parameter shorthand detection: if `parameters` is a plain object and NOT a `ZodType`, wrap with `z.object()`
- Check `parameters instanceof z.ZodType` (or use Zod v4's `z.core.$brand` check) to distinguish shorthand from full schema
- File location: `packages/nestjs-mcp/src/decorators/tool.decorator.ts`
- Export from `packages/nestjs-mcp/src/decorators/index.ts`
- **FastMCP parity:** `timeout` maps to FastMCP's `timeout` option (FastMCP uses seconds; we use milliseconds for NestJS convention). `mask` maps to FastMCP's `mask_error_details` per-tool option. A module-level `maskErrorDetails` default is defined in CORE-012; per-tool `mask` overrides it. The pipeline runner (CORE-010) is responsible for enforcing timeout abort and error masking at execution time.
