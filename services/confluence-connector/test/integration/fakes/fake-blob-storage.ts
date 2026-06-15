import { Readable } from 'node:stream';
import type { Dispatcher } from 'undici';
import { MockAgent } from 'undici';
import type { FakeUniqueApi } from './fake-unique-api';

const FAKE_BLOB_ORIGIN = 'https://fake-blob.local';

/**
 * Intercepts blob upload PUTs (writeUrl) emitted by IngestionService and routes
 * the body bytes back to FakeUniqueApi.completeUpload.
 *
 * Powered by undici MockAgent so we can plug it into IngestionService through its
 * `dispatcher` constructor parameter.
 */
export class FakeBlobStorage {
  private readonly mockAgent: MockAgent;

  public constructor(private readonly unique: FakeUniqueApi) {
    this.mockAgent = new MockAgent();
    this.mockAgent.disableNetConnect();

    const pool = this.mockAgent.get(FAKE_BLOB_ORIGIN);
    pool
      .intercept({
        method: 'PUT',
        path: /^\/blob\/[^/]+$/,
      })
      .reply(200, async (opts) => {
        const body = await readBody(opts.body);
        const token = extractToken(opts.path);
        const result = this.unique.completeUpload(token, body);
        return result.matched ? '' : JSON.stringify({ status: 'unmatched-upload' });
      })
      .persist();
  }

  public asDispatcher(): Dispatcher {
    return this.mockAgent;
  }
}

function extractToken(path: string): string {
  const match = /\/blob\/([^/?#]+)/.exec(path);
  if (!match || !match[1]) {
    throw new Error(`Could not extract upload token from path: ${path}`);
  }
  return match[1];
}

async function readBody(body: unknown): Promise<Buffer> {
  if (!body) {
    return Buffer.alloc(0);
  }
  if (Buffer.isBuffer(body)) {
    return body;
  }
  if (typeof body === 'string') {
    return Buffer.from(body, 'utf-8');
  }
  if (body instanceof Uint8Array) {
    return Buffer.from(body);
  }
  if (body instanceof Readable || isAsyncIterable(body)) {
    const chunks: Buffer[] = [];
    for await (const chunk of body as AsyncIterable<Buffer | string>) {
      chunks.push(typeof chunk === 'string' ? Buffer.from(chunk, 'utf-8') : Buffer.from(chunk));
    }
    return Buffer.concat(chunks);
  }
  throw new Error(`Unsupported request body type: ${typeof body}`);
}

function isAsyncIterable(value: unknown): value is AsyncIterable<unknown> {
  return (
    value !== null &&
    typeof value === 'object' &&
    Symbol.asyncIterator in (value as Record<string | symbol, unknown>)
  );
}
