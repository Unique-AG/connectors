import type { ImageContent, TextContent } from '@modelcontextprotocol/sdk/types.js';

export interface AudioContent {
  type: 'audio';
  data: string;
  mimeType: string;
}

export interface EmbeddedResourceContent {
  type: 'resource';
  resource: {
    uri: string;
    blob: string;
    mimeType?: string;
  };
}

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

  public static file(pathOrData: Buffer, mimeType?: string): { content: [EmbeddedResourceContent] } {
    const blob = pathOrData.toString('base64');
    return { content: [{ type: 'resource', resource: { uri: '', blob, mimeType } }] };
  }

  public static error(msg: string): { content: [TextContent]; isError: true } {
    return { content: [{ type: 'text', text: msg }], isError: true };
  }

  public static readonly Audio = McpContent.audio;
  public static readonly File = McpContent.file;
}
