import { Readable } from 'node:stream';
import type { Dispatcher } from 'undici';
import { MockAgent } from 'undici';
import type { FakeUniqueApi } from './fake-unique-api';

const FAKE_BLOB_ORIGIN = 'https://fake-blob.local';

/**
 * Fake blob store for tests.
 *
 * Ingestion is two separate calls, not one. First `registerContent` tells
 * Unique a file exists; Unique creates a record (with an id) but no bytes yet,
 * and returns a `writeUrl`. Then the connector PUTs the bytes to that url. The
 * PUT carries only the url and the body, not the file id, so something has to
 * answer: which file do these bytes belong to?
 *
 * The token in the url is that link. When `registerContent` runs, FakeUniqueApi
 * mints a random token, bakes it into `https://fake-blob.local/blob/<token>`,
 * and remembers `token -> file` in its pending-uploads map. This fake catches
 * the PUT, pulls the token back out of the path, and calls
 * `FakeUniqueApi.completeUpload(token, bytes)`, which looks up that file and
 * finally fills in its body. Only then can the body/bodyHash/bodySize
 * assertions see anything. (This mirrors real pre-signed blob urls: the token
 * in the url is the address of the destination blob.)
 *
 * This fake stays dumb on purpose: it just catches the PUT and forwards
 * `(token, bytes)`. The token-to-file correlation lives in FakeUniqueApi, which
 * owns the file records.
 *
 * It is built on undici's MockAgent so it can be passed to IngestionService as
 * its `dispatcher`. Network access is turned off, so any PUT we forget to catch
 * fails loudly instead of going out to the internet.
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

// The intercept matcher guarantees the path is `/blob/<token>` with no further
// slashes, so the last segment is the token.
function extractToken(path: string): string {
  const token = path.split('/').pop();
  if (!token) {
    throw new Error(`Could not extract upload token from path: ${path}`);
  }
  return token;
}

// IngestionService sends either a Buffer (uploadBuffer) or a Readable stream
// (uploadStream); those are the only two shapes we handle.
async function readBody(body: unknown): Promise<Buffer> {
  if (!body) {
    return Buffer.alloc(0);
  }
  if (Buffer.isBuffer(body)) {
    return body;
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
