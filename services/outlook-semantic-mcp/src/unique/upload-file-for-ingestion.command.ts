import assert from 'node:assert';
import { Readable } from 'node:stream';
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

  public async run({ uploadUrl, content, mimeType }: UploadFileForIngestionInput): Promise<{
    byteSize: number;
  }> {
    const url = new URL(this.correctWriteUrl(uploadUrl));
    const path = `${url.pathname}${url.search}`;

    let byteSize = 0;

    const outputStream = content.pipeThrough(
      new TransformStream({
        transform: (chunk, controller) => {
          byteSize += chunk.length;
          controller.enqueue(chunk);
        },
      }),
    );
    await this.httpClientService.request({
      method: 'PUT',
      path,
      origin: url.origin,
      headers: {
        'Content-Type': mimeType || 'application/octet-stream',
        'x-ms-blob-type': 'BlockBlob',
      },
      body: Readable.from(outputStream),
      // @ts-expect-error: this is nodejs fetch and requires `half` to be specified as per fetch WHATWG
      // and nodejs types get merged with browser types which do not have such property
      // - see https://undici.nodejs.org/#/?id=requestduplex
      duplex: 'half',
    });

    return { byteSize };
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
