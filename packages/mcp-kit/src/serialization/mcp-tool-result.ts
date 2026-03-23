import type { AudioContent, EmbeddedResource, ImageContent, ResourceLink, TextContent } from '@modelcontextprotocol/sdk/types.js';

export class McpToolResult {
  public readonly content: Array<TextContent | ImageContent | AudioContent | ResourceLink | EmbeddedResource>;
  public readonly structuredContent?: Record<string, unknown>;
  public readonly isError?: boolean;
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
