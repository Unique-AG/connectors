import assert from 'node:assert';

/**
 * A content payload paired with its exact byte size, ready to be uploaded with an explicit
 * `Content-Length` header.
 */
export interface SizedContent {
  stream: ReadableStream<Uint8Array<ArrayBuffer>>;
  size: number;
}

/**
 * Adapts an HTTP download `Response` (e.g. an MS Graph `/content` fetch) into a
 * {@link SizedContent} with a known byte size.
 *
 * The `Content-Length` header is trusted only for identity-encoded responses: Node's fetch
 * (undici) transparently decompresses a gzip/deflate/br `body` stream while the header keeps the
 * *compressed* size, so streaming it under that length would truncate the upload. When the length
 * cannot be trusted (content-encoded, or absent) the body is buffered in memory purely to measure
 * it — used for small, compressible payloads; large media is served uncompressed and takes the
 * zero-copy streaming path.
 */
export async function readSizedContent(response: Response): Promise<SizedContent> {
  assert.ok(response.body, 'Content response has no body');

  const advertised = response.headers.get('content-length');
  const encoding = response.headers.get('content-encoding');
  const isIdentityEncoding = encoding === null || encoding === '' || encoding === 'identity';

  if (
    isIdentityEncoding &&
    advertised !== null &&
    advertised !== '' &&
    Number.isFinite(Number(advertised))
  ) {
    return {
      stream: response.body as ReadableStream<Uint8Array<ArrayBuffer>>,
      size: Number(advertised),
    };
  }

  const buffered = new Uint8Array(await response.arrayBuffer());
  return {
    stream: new ReadableStream({
      start(controller) {
        controller.enqueue(buffered);
        controller.close();
      },
    }),
    size: buffered.byteLength,
  };
}
