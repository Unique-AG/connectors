import assert from 'node:assert';
import { UniqueConfig } from '~/config';
import { HttpClientService } from '~/http-client/http-client.service';

export interface UploadFileForIngestionInput {
  uploadUrl: string;
  content: ReadableStream;
  mimeType: string;
}

export class UploadFileForIngestionCommand {
  public constructor(
    private readonly uniqueConfig: UniqueConfig,
    private readonly httpClientService: HttpClientService,
  ) {}

  public async run({ uploadUrl, content, mimeType }: UploadFileForIngestionInput): Promise<void> {
    const url = new URL(this.correctWriteUrl(uploadUrl));
    const path = `${url.pathname}${url.search}`;

    // TODO: Understand why this works because it seems the unidici library makes the request
    // than node-ingestion returns 500 than unidici does a retry and the retry succeds.
    await this.httpClientService.request({
      method: 'PUT',
      path,
      origin: url.origin,
      headers: {
        'Content-Type': mimeType || 'application/octet-stream',
        'x-ms-blob-type': 'BlockBlob',
      },
      // @ts-expect-error: The type of content is supported it's a ReadableStream but somehow he confuses
      // the node types with the browser types. The body has to be a ReadableStream and not a Readable
      // from node for the upload to work.
      body: content,
      duplex: 'half',
    });
  }

  // HACK:
  // When running in internal auth mode, rewrite the writeUrl to route through the ingestion
  // service's scoped upload endpoint. This enables internal services to upload files without
  // requiring external network access (hairpinning).
  // Ideally we should fix this somehow in the service itself by using a separate property or make
  // writeUrl configurable, but for now this hack lets us avoid hairpinning issues in the internal
  // upload flows.
  private correctWriteUrl(writeUrl: string): string {
    if (this.uniqueConfig.serviceAuthMode === 'external') {
      return writeUrl;
    }
    const url = new URL(writeUrl);
    const key = url.searchParams.get('key');
    assert.ok(key, 'writeUrl is missing key parameter');
    return `${this.uniqueConfig.ingestionServiceBaseUrl}/scoped/upload?key=${encodeURIComponent(key)}`;
  }
}
