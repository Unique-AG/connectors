import assert from 'node:assert';
import { ProxyService } from '@unique-ag/proxy';
import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { fetch } from 'undici';
import { UniqueConfigNamespaced } from '~/config';

export interface UploadFileForIngestionInput {
  uploadUrl: string;
  content: Buffer;
  mimeType: string;
}

@Injectable()
export class UploadFileForIngestionCommand {
  public constructor(
    private configService: ConfigService<UniqueConfigNamespaced, true>,
    private readonly proxyService: ProxyService,
  ) {}

  public async run({ uploadUrl, content, mimeType }: UploadFileForIngestionInput): Promise<void> {
    // Use undici fetch with an explicit dispatcher from ProxyService.
    // Do NOT compose retry — undici retry on 500s previously corrupted Azure blobs by
    // re-sending only the first chunk. Bare getDispatcher has no retry composed.
    const dispatcher = this.proxyService.getDispatcher({ mode: 'for-external-only' });
    await fetch(this.correctWriteUrl(uploadUrl), {
      method: 'PUT',
      headers: {
        'Content-Length': String(content.byteLength),
        'Content-Type': mimeType || 'application/octet-stream',
        'x-ms-blob-type': 'BlockBlob',
      },
      body: content,
      dispatcher,
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
