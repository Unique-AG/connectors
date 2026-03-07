# TEST-002: McpTestClient

## Summary
Create `McpTestClient` — an ergonomic wrapper around the SDK `Client` designed for test assertions. Provides typed methods for calling tools, listing resources, reading resources, listing prompts, and calling prompts. Throws on MCP errors (`isError: true`) so tests can use standard `expect(...).rejects.toThrow()` patterns instead of checking error flags manually.

## Background / Context
The raw SDK `Client` returns results with `isError` flags and untyped content arrays. In tests, this leads to verbose assertion boilerplate:

```typescript
// Without McpTestClient (verbose)
const result = await client.callTool({ name: 'search', arguments: { q: 'test' } });
expect(result.isError).toBe(false);
const text = (result.content as Array<{ type: string; text: string }>)[0].text;
expect(JSON.parse(text)).toEqual(expected);

// With McpTestClient (clean)
const result = await testClient.callTool('search', { q: 'test' });
expect(result).toEqual(expected);
```

`McpTestClient` wraps the SDK `Client` and provides:
- Simplified method signatures (`callTool(name, args)` instead of `callTool({ name, arguments })`)
- Auto-deserialization of text content to objects (when JSON)
- Automatic error throwing for `isError: true` responses
- Typed return values

## Acceptance Criteria
- [ ] `McpTestClient` wraps an SDK `Client` instance (injected via constructor)
- [ ] `callTool(name: string, args?: Record<string, unknown>): Promise<unknown>` — calls tool, deserializes result
  - If response has `structuredContent`, returns it directly
  - If response has single text content that is valid JSON, parses and returns it
  - If response has single text content that is not JSON, returns the string
  - If response has multiple content blocks, returns the array
  - If response has `isError: true`, throws `McpToolError` with the error message
- [ ] `listTools(): Promise<ToolInfo[]>` — returns array of tool metadata (name, description, inputSchema)
- [ ] `readResource(uri: string): Promise<ResourceContent[]>` — reads resource by URI, returns content array
- [ ] `listResources(): Promise<ResourceInfo[]>` — returns array of resource metadata
- [ ] `callPrompt(name: string, args?: Record<string, string>): Promise<PromptMessage[]>` — calls prompt, returns messages
- [ ] `listPrompts(): Promise<PromptInfo[]>` — returns array of prompt metadata
- [ ] `McpToolError` is a custom Error class with `name: 'McpToolError'`, `message` (from error content), and `content` (raw content array)
- [ ] All methods have proper TypeScript types

## BDD Scenarios

```gherkin
Feature: MCP test client
  An ergonomic wrapper around the SDK Client for test assertions,
  providing auto-deserialization and error-as-exception semantics.

  Rule: Tool results are automatically deserialized

    Scenario: JSON text content is parsed into an object
      Given a tool "add" that returns { sum: 5 } as JSON text
      When the test client calls "add" with a: 2, b: 3
      Then the returned value is the object { sum: 5 }

    Scenario: Structured content is returned directly
      Given a tool "search" that returns structured content via an output schema
      When the test client calls "search" with query: "test"
      Then the returned value is the structured content object

    Scenario: Non-JSON text is returned as a string
      Given a tool "greet" that returns plain text "Hello, world!"
      When the test client calls "greet"
      Then the returned value is the string "Hello, world!"

    Scenario: Multiple content blocks are returned as an array
      Given a tool "multi_content" that returns text and image content blocks
      When the test client calls "multi_content"
      Then the returned value is the raw content array

  Rule: Tool errors throw exceptions for easy assertion

    Scenario: Error response throws McpToolError
      Given a tool "fail" that returns an error "Something went wrong"
      When the test client calls "fail"
      Then a McpToolError is thrown with message "Something went wrong"
      And the error contains the raw MCP content array

    Scenario: Unknown tool throws an error
      Given no tool named "nonexistent" is registered
      When the test client calls "nonexistent"
      Then an error is thrown indicating the tool does not exist

  Rule: Listing operations return typed metadata

    Scenario: Listing tools returns metadata for all registered tools
      Given a test module with 3 registered tools
      When the test client lists tools
      Then 3 tool entries are returned, each with name, description, and input schema

    Scenario: Listing prompts returns metadata for all registered prompts
      Given a test module with 2 registered prompts
      When the test client lists prompts
      Then 2 prompt entries are returned with their metadata

  Rule: Resources and prompts can be read and called

    Scenario: Reading a resource returns its content
      Given a resource at "config://app/settings" containing { theme: "dark" }
      When the test client reads resource "config://app/settings"
      Then the resource content is returned

    Scenario: Calling a prompt returns its messages
      Given a prompt "compose-outreach" that generates messages
      When the test client calls prompt "compose-outreach" with recipient: "user@test.com"
      Then an array of prompt messages is returned with the expected content
```

## Dependencies
- **Depends on:** none (standalone wrapper around SDK `Client`)
- **Blocks:** TEST-001 — `McpTestingModule` exposes `McpTestClient` as `testModule.client`

## Technical Notes
- File location: `packages/nestjs-mcp-testing/src/mcp-test-client.ts`
- `McpToolError` file: `packages/nestjs-mcp-testing/src/errors/mcp-tool-error.ts`
- The SDK `Client` is from `@modelcontextprotocol/sdk/client/index.js`. It has methods: `callTool()`, `listTools()`, `readResource()`, `listResources()`, `getPrompt()`, `listPrompts()`.
- SDK `callTool` signature: `callTool({ name: string, arguments: Record<string, unknown> }, resultSchema?, options?)` returns `CallToolResult` with `{ content: Content[], isError?: boolean, structuredContent?: unknown }`.
- Deserialization logic for `callTool`:
  ```typescript
  if (result.structuredContent !== undefined) return result.structuredContent;
  if (result.isError) throw new McpToolError(extractErrorMessage(result.content), result.content);
  if (result.content.length === 1 && result.content[0].type === 'text') {
    try { return JSON.parse(result.content[0].text); }
    catch { return result.content[0].text; }
  }
  return result.content;
  ```
- `ToolInfo`, `ResourceInfo`, `PromptInfo` can be type aliases for the SDK's list result types, or simplified interfaces for better test ergonomics.
- The `McpTestClient` constructor takes the SDK `Client` directly: `constructor(private readonly client: Client)`. Connection setup is handled by `McpTestingModule`.
