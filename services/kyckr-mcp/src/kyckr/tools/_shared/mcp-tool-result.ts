export interface McpTextBlock {
  type: 'text';
  text: string;
}

export interface McpResourceBlock {
  type: 'resource';
  resource: {
    uri: string;
    mimeType: string;
    blob: string;
  };
}

export type McpContentBlock = McpTextBlock | McpResourceBlock;

export interface McpMixedToolResult<T> {
  content: McpContentBlock[];
  structuredContent: T;
}

export type McpToolResult<T> = T | McpMixedToolResult<T>;
