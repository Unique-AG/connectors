import type { AudioContent, EmbeddedResource, ImageContent, ResourceLink, TextContent } from '@modelcontextprotocol/sdk/types.js';

export type { AudioContent, EmbeddedResource, ResourceLink };

export class McpContent {
  public static text(text: string): { content: [TextContent] } {
    return { content: [{ type: 'text', text }] };
  }

  public static image(data: Buffer, mimeType: string): { content: [ImageContent] } {
    return { content: [{ type: 'image', data: data.toString('base64'), mimeType }] };
  }

  public static audio(data: Buffer | string, mimeType = 'audio/mpeg'): { content: [AudioContent] } {
    const base64 = typeof data === 'string' ? data : data.toString('base64');
    return { content: [{ type: 'audio', data: base64, mimeType }] };
  }

  public static file(uri: string, data: Buffer, mimeType?: string): { content: [EmbeddedResource] } {
    return {
      content: [{ type: 'resource', resource: { uri, blob: data.toString('base64'), mimeType } }],
    };
  }

  public static resourceLink(
    uri: string,
    name: string,
    options?: { title?: string; description?: string; mimeType?: string },
  ): { content: [ResourceLink] } {
    return {
      content: [{ type: 'resource_link', uri, name, ...options }],
    };
  }

  public static error(msg: string): { content: [TextContent]; isError: true } {
    return { content: [{ type: 'text', text: msg }], isError: true };
  }
}
