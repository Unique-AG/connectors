import type { AudioContent, EmbeddedResource, ImageContent, ResourceLink, TextContent } from '@modelcontextprotocol/sdk/types.js';

/** Re-exported from the MCP SDK — represents base64-encoded audio sent inline in a tool response. */
export type { AudioContent };
/** Re-exported from the MCP SDK — wraps an inline resource (blob or text) embedded directly in a tool response. */
export type { EmbeddedResource };
/** Re-exported from the MCP SDK — a lightweight reference to an external resource by URI, not inline content. */
export type { ResourceLink };

/** Static factory for constructing single-item MCP content arrays returned by tool handlers. */
export class McpContent {
  /** Returns a plain-text content item. */
  public static text(text: string): { content: [TextContent] } {
    return { content: [{ type: 'text', text }] };
  }

  /** Returns a base64-encoded image content item. */
  public static image(data: Buffer, mimeType: string): { content: [ImageContent] } {
    return { content: [{ type: 'image', data: data.toString('base64'), mimeType }] };
  }

  /** Returns a base64-encoded audio content item. Accepts a raw Buffer or an already-encoded base64 string. */
  public static audio(data: Buffer | string, mimeType = 'audio/mpeg'): { content: [AudioContent] } {
    const base64 = typeof data === 'string' ? data : data.toString('base64');
    return { content: [{ type: 'audio', data: base64, mimeType }] };
  }

  /**
   * Returns an inline embedded-resource content item containing the raw file bytes.
   * @param uri Identifies the resource — may be a data URI or the URI of a registered MCP resource.
   */
  public static file(uri: string, data: Buffer, mimeType?: string): { content: [EmbeddedResource] } {
    return {
      content: [{ type: 'resource', resource: { uri, blob: data.toString('base64'), mimeType } }],
    };
  }

  /**
   * Returns a resource-link content item — a reference to an external resource, not inline content.
   * The client resolves the resource separately using the provided URI.
   */
  public static resourceLink(
    uri: string,
    name: string,
    options?: { title?: string; description?: string; mimeType?: string },
  ): { content: [ResourceLink] } {
    return {
      content: [{ type: 'resource_link', uri, name, ...options }],
    };
  }

  /** Returns a text content item flagged as an error result. */
  public static error(msg: string): { content: [TextContent]; isError: true } {
    return { content: [{ type: 'text', text: msg }], isError: true };
  }
}
