import assert from 'node:assert';
import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { UniqueConfigNamespaced } from '~/config';

export interface UploadFileForIngestionInput {
  uploadUrl: string;
  contentLength: number;
  content: ReadableStream;
  mimeType: string;
}

@Injectable()
export class UploadFileForIngestionCommand {
  public constructor(private configService: ConfigService<UniqueConfigNamespaced, true>) {}

  public async run({
    uploadUrl,
    contentLength,
    content,
    mimeType,
  }: UploadFileForIngestionInput): Promise<void> {
    // We use fetch instead of unidici because while testing upload without contentLength the unidici library
    // managed to create broken files on azure because the initial upload call was returning 500 and unidici
    // retried and then we succeded because they sent only the first chunk of bites. In order to minimise broken
    // files it's safer to use plain fetch without any magic underneath.
    await fetch(this.correctWriteUrl(uploadUrl), {
      method: 'PUT',
      headers: {
        // UN-17418: Check why this works in Teams-MCP without the content length because it seems from azure
        // docs it should not work without the contentLength up front there is another request which we
        // can use to upload it in chunks properly without knowing the content length.
        'Content-Length': `${contentLength}`,
        'Content-Type': mimeType || 'application/octet-stream',
        'x-ms-blob-type': 'BlockBlob',
      },
      body: content,
      // @ts-expect-error: The type of content is supported it's a ReadableStream but somehow he confuses
      // the node types with the browser types. The body has to be a ReadableStream and not a Readable
      // from node for the upload to work.
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
    const uniqueConfig = this.configService.get('unique', { infer: true });
    if (uniqueConfig.serviceAuthMode === 'external') {
      return writeUrl;
    }
    const url = new URL(writeUrl);
    const key = url.searchParams.get('key');
    assert.ok(key, 'writeUrl is missing key parameter');
    return `${uniqueConfig.ingestionServiceBaseUrl}/scoped/upload?key=${encodeURIComponent(key)}`;
  }
}
