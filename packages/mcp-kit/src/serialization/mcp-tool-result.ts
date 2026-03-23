import type { AudioContent, EmbeddedResource, ImageContent, ResourceLink, TextContent } from '@modelcontextprotocol/sdk/types.js';

/**
 * Explicit result container for tool handlers that need full control over content,
 * structured output, error signalling, or response metadata.
 * Return this instead of a plain value when any of those fields must be set directly.
 */
export class McpToolResult {
  /** One or more content items sent to the client in the MCP response. */
  public readonly content: Array<TextContent | ImageContent | AudioContent | ResourceLink | EmbeddedResource>;

  /** Machine-readable structured output; must conform to the tool's declared output schema when present. */
  public readonly structuredContent?: Record<string, unknown>;

  /** When `true`, signals to the client that the tool call produced an error result. */
  public readonly isError?: boolean;

  /** Arbitrary metadata forwarded as `_meta` in the MCP wire response. */
  public readonly meta?: Record<string, unknown>;

  public constructor(params: {
    content: Array<TextContent | ImageContent | AudioContent | ResourceLink | EmbeddedResource>;
    structuredContent?: Record<string, unknown>;
    isError?: boolean;
    meta?: Record<string, unknown>;
  }) {
    this.content = params.content;
    this.structuredContent = params.structuredContent;
    this.isError = params.isError;
    this.meta = params.meta;
  }
}
