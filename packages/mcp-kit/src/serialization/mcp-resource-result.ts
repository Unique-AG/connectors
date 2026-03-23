import type { TextResourceContents, BlobResourceContents } from '@modelcontextprotocol/sdk/types.js';

export type ResourceContents = TextResourceContents | BlobResourceContents;

/**
 * Explicit result container for resource handlers that need to return one or more
 * resource contents in the MCP wire format.
 */
export class McpResourceResult {
  /** The list of resource content items included in the response. */
  public readonly contents: ResourceContents[];

  public constructor(params: { contents: ResourceContents[] }) {
    this.contents = params.contents;
  }
}
