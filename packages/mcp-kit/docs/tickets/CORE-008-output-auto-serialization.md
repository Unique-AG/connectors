# CORE-008: Output auto-serialization (McpContent)

## Summary
Implement the output auto-serialization layer that converts tool handler return values into MCP wire format, plus the `McpContent` helper class with static factory methods for explicit content creation. This eliminates boilerplate where every tool must manually construct `{ content: [{ type: 'text', text: ... }] }`.

## Background / Context
The output auto-serialization layer converts tool handler return values into MCP wire format:
1. Primitive handling (`string/number/boolean` -> text content)
2. `structuredContent` support when `outputSchema` is defined
3. `McpContent` helper class with `text()`, `image()`, `error()` static methods
4. Pass-through detection for already-formatted responses

This logic is a standalone serializer reusable by resource and prompt handlers too.

## Acceptance Criteria
- [ ] `string` return -> `{ content: [{ type: 'text', text: value }] }`
- [ ] `number` return -> `{ content: [{ type: 'text', text: String(value) }] }`
- [ ] `boolean` return -> `{ content: [{ type: 'text', text: String(value) }] }`
- [ ] `object` (no outputSchema) -> `{ content: [{ type: 'text', text: JSON.stringify(value, null, 2) }] }`
- [ ] `object` (with outputSchema) -> `{ structuredContent: value, content: [{ type: 'text', text: JSON.stringify(value, null, 2) }] }`
- [ ] `object` with outputSchema validates against schema; throws `McpError(InternalError)` on validation failure
- [ ] Pass-through: if return value already has `content` array, return as-is
- [ ] `null` / `undefined` return -> `{ content: [{ type: 'text', text: '' }] }`
- [ ] `McpContent.text(s)` -> `{ content: [{ type: 'text', text: s }] }`
- [ ] `McpContent.image(buffer, mimeType)` -> `{ content: [{ type: 'image', data: base64, mimeType }] }`
- [ ] `McpContent.error(msg)` -> `{ content: [{ type: 'text', text: msg }], isError: true }`
- [ ] `McpToolResult` class with optional `meta: Record<string, unknown>` field — emitted as `_meta` on the MCP wire response
- [ ] `McpToolResult` supports `content`, `structuredContent`, `isError`, and `meta` fields
- [ ] Pass-through detection also preserves `_meta` from already-formatted responses
- [ ] `McpResourceResult` class for multi-content resource responses: `contents: Array<{ uri: string; text?: string; blob?: string; mimeType?: string }>`
- [ ] `McpResourceResult` supports returning multiple content items from a single resource handler
- [ ] `McpContent.audio(data: Buffer | string, mimeType?: string)` helper returns `AudioContent` — audio data encoded as base64 with MIME type (default: `audio/mpeg`)
- [ ] `McpContent.file(pathOrData: string | Buffer, mimeType?: string)` helper returns `EmbeddedResource` with blob content — for file attachments in tool responses
- [ ] `Audio` and `File` aliased exports from `McpContent` for FastMCP naming compatibility (i.e. `McpContent.Audio === McpContent.audio`)
- [ ] `ToolError(message: string)` — thrown in tool handlers, message ALWAYS forwarded to client even when `maskErrorDetails: true` (unlike generic `Error` which gets masked)
- [ ] `ResourceError(message: string)` — thrown in resource handlers, message ALWAYS forwarded to client even when `maskErrorDetails: true`
- [ ] `PromptError(message: string)` — thrown in prompt handlers, message ALWAYS forwarded to client even when `maskErrorDetails: true`
- [ ] Generic `Error` thrown in handlers → message masked when `maskErrorDetails: true`; `ToolError`/`ResourceError`/`PromptError` always propagate message to client
- [ ] `ResourceResult` class: `{ contents: string | Buffer | ResourceContent[], meta?: Record<string, unknown> }`
- [ ] `ResourceContent` inner type: `{ content: string | Buffer | object, mimeType?: string, meta?: Record<string, unknown> }` — `object` values auto-serialized to JSON
- [ ] Multi-content `ResourceResult` supported: one resource handler can return multiple content items
- [ ] Serializer function and `McpContent` class exported from `@unique-ag/nestjs-mcp`

## BDD Scenarios

```gherkin
Feature: Output auto-serialization converts handler return values to MCP wire format

  Rule: Primitive return values are auto-converted to text content

    Scenario Outline: Primitive values become text content
      Given a tool handler that returns <value>
      When the MCP client receives the response
      Then the response contains a single text content block with text "<text>"

      Examples:
        | value         | text        |
        | "hello world" | hello world |
        | 42            | 42          |
        | true          | true        |

    Scenario Outline: Null and undefined become empty text
      Given a tool handler that returns <value>
      When the MCP client receives the response
      Then the response contains a single text content block with empty text

      Examples:
        | value     |
        | null      |
        | undefined |

  Rule: Object return values are serialized based on output schema

    Scenario: Object without output schema becomes JSON text
      Given a tool with no output schema that returns an object with key "status" and value "ok"
      When the MCP client receives the response
      Then the response contains a text content block with the JSON representation

    Scenario: Object with output schema produces structured content
      Given a tool with an output schema requiring a "count" integer
      And the handler returns an object with count 5
      When the MCP client receives the response
      Then the response includes structured content with count 5
      And a text fallback with the JSON representation is also included

    Scenario: Object violating the output schema produces an error
      Given a tool with an output schema requiring a "count" integer
      And the handler returns an object with count "not a number"
      When the framework serializes the result
      Then an internal error is raised indicating the output does not match the schema

  Rule: Already-formatted responses pass through unchanged

    Scenario: Handler returning MCP content format is not re-wrapped
      Given a tool handler that returns a pre-formatted content array with text "custom"
      When the MCP client receives the response
      Then the response contains exactly the text "custom" without additional wrapping

  Rule: McpContent helpers produce correctly typed content

    Scenario: McpContent.error marks the response as an error
      Given a tool handler that returns an error content block with message "Something went wrong"
      When the MCP client receives the response
      Then the response is marked as an error
      And the text is "Something went wrong"

    Scenario: McpContent.image produces base64-encoded image content
      Given a tool handler that returns an image from a PNG buffer
      When the MCP client receives the response
      Then the response contains an image content block
      And the data is base64-encoded
      And the MIME type is "image/png"

    Scenario: McpContent.audio produces base64-encoded audio content
      Given a tool handler that returns audio from an MP3 buffer
      When the MCP client receives the response
      Then the response contains an audio content block
      And the data is base64-encoded
      And the MIME type is "audio/mpeg"

  Rule: McpToolResult supports metadata on the wire

    Scenario: Tool result with meta includes metadata in the response
      Given a tool handler that returns a result with meta key "unique.app/trace-id" set to "abc-123"
      When the MCP client receives the response
      Then the response metadata includes "unique.app/trace-id" with value "abc-123"

    Scenario: Tool result without meta omits metadata from the response
      Given a tool handler that returns a result with no meta
      When the MCP client receives the response
      Then the response does not include a metadata field

  Rule: Resource handlers can return multiple content items

    Scenario: Resource returns multiple content items
      Given a resource handler that returns two content items for URIs "config://app/db" and "config://app/cache"
      When the MCP client reads the resource
      Then the response contains 2 content items with their respective URIs

    Scenario: Resource returns binary blob content
      Given a resource handler that returns a PNG blob for URI "files://logo.png"
      When the MCP client reads the resource
      Then the response contains a blob content item with base64 data

  Rule: Error masking distinguishes intentional from unintentional errors

    Scenario: ToolError message is always forwarded to the client
      Given a tool handler that throws a ToolError with message "Invalid API key"
      And error masking is enabled
      When the MCP client receives the error response
      Then the error message is "Invalid API key"

    Scenario: Generic Error message is masked when masking is enabled
      Given a tool handler that throws a generic error "Internal database connection failed"
      And error masking is enabled
      When the MCP client receives the error response
      Then the error message is a generic "An internal error occurred"
      And the original error details are not exposed
```

## Dependencies
- Depends on: INFRA-001 — package must exist
- Blocks: CORE-013 — handlers use serializer to format return values

## Technical Notes
- Serializer function signature: `formatToolResult(value: unknown, outputSchema?: z.ZodTypeAny): ToolResult`
- Pass-through detection: check `value && typeof value === 'object' && 'content' in value && Array.isArray(value.content)`
- `McpContent` is a class with only static methods (no instances):
  ```typescript
  export class McpContent {
    static text(s: string) { return { content: [{ type: 'text' as const, text: s }] }; }
    static image(buf: Buffer, mimeType: string) { return { content: [{ type: 'image' as const, data: buf.toString('base64'), mimeType }] }; }
    static error(msg: string) { return { content: [{ type: 'text' as const, text: msg }], isError: true }; }
  }
  ```
- `McpToolResult` class:
  ```typescript
  export class McpToolResult {
    content: Array<TextContent | ImageContent | AudioContent>;
    structuredContent?: Record<string, unknown>;
    isError?: boolean;
    meta?: Record<string, unknown>;              // emitted as `_meta` on wire

    constructor(params: {
      content: Array<TextContent | ImageContent | AudioContent>;
      structuredContent?: Record<string, unknown>;
      isError?: boolean;
      meta?: Record<string, unknown>;
    });
  }
  ```
- `McpResourceResult` class:
  ```typescript
  export class McpResourceResult {
    contents: Array<{
      uri: string;
      text?: string;
      blob?: string;
      mimeType?: string;
    }>;

    constructor(params: { contents: Array<{ uri: string; text?: string; blob?: string; mimeType?: string }> });
  }
  ```
- Pass-through detection updated: check for `McpToolResult` instance OR raw `{ content: [...] }` shape
- When `meta` is present on `McpToolResult`, the serializer maps it to `_meta` in the wire response
- **FastMCP parity:** `McpToolResult.meta` maps to FastMCP `ToolResult(meta=...)`. `McpResourceResult` maps to FastMCP `ResourceResult` multi-content pattern
- File locations:
  - `packages/nestjs-mcp/src/serialization/format-tool-result.ts`
  - `packages/nestjs-mcp/src/serialization/mcp-content.ts`
  - `packages/nestjs-mcp/src/serialization/mcp-tool-result.ts`
  - `packages/nestjs-mcp/src/serialization/mcp-resource-result.ts`
- Export all from `packages/nestjs-mcp/src/index.ts`
