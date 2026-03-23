/** An icon associated with an MCP tool, resource, or prompt for display in client UIs. */
export interface McpIcon {
  /** Publicly accessible URI pointing to the icon image. */
  uri: string;
  /** MIME type of the image (e.g. `"image/png"`). Omit to let the client infer it. */
  mimeType?: string;
}
