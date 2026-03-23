/** A single resource item returned in an MCP resource response. Carries either text or a base64-encoded blob. */
export interface ResourceContent {
  /** The URI that uniquely identifies this resource. */
  uri: string;
  /** Text body of the resource, mutually exclusive with `blob`. */
  text?: string;
  /** Base64-encoded binary body of the resource, mutually exclusive with `text`. */
  blob?: string;
  mimeType?: string;
}

/**
 * Explicit result container for resource handlers that need to return one or more
 * resource contents in the MCP wire format.
 */
export class McpResourceResult {
  /** The list of resource content items included in the response. */
  public readonly contents: ResourceContent[];

  public constructor(params: { contents: ResourceContent[] }) {
    this.contents = params.contents;
  }
}
