export interface ResourceContent {
  uri: string;
  text?: string;
  blob?: string;
  mimeType?: string;
}

export class McpResourceResult {
  public readonly contents: ResourceContent[];

  public constructor(params: { contents: ResourceContent[] }) {
    this.contents = params.contents;
  }
}
