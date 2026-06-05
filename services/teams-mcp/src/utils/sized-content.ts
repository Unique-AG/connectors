import assert from 'node:assert';

/**
 * A content payload paired with its exact byte size, ready to be uploaded with an explicit
 * `Content-Length` header.
 */
export interface SizedContent {
  stream: ReadableStream<Uint8Array<ArrayBuffer>>;
  size: number;
}

/** Max bytes of an unexpected/error body we read back into a thrown error for diagnosis. */
const DIAGNOSTIC_BODY_LIMIT = 2048;

/**
 * Content types that indicate an error envelope or redirect/login page rather than the media we
 * asked for. MS Graph errors are JSON, Azure Blob/SAS errors are XML, and auth interstitials are
 * HTML — none of which should ever be uploaded as recording/transcript content.
 */
const NON_MEDIA_CONTENT_TYPES = ['application/json', 'application/xml', 'text/xml', 'text/html'];

/**
 * Adapts an HTTP download `Response` (e.g. an MS Graph `/content` fetch) into a
 * {@link SizedContent} with a known byte size.
 *
 * Per the Graph docs a healthy recording/transcript download is `200 OK` with the media bytes
 * (e.g. `Content-Type: video/mp4`). A non-OK status — or a JSON/XML/HTML body — means we got an
 * error envelope, SAS-expiry notice, or login page instead of the content; uploading that would
 * silently store a tiny corrupt blob. We fail loudly in that case and include the (small) body in
 * the error to surface the real cause.
 *
 * For a valid response the `Content-Length` header is trusted only when the body is not
 * content-encoded: Node's fetch (undici) transparently decompresses a gzip/deflate/br `body`
 * stream while the header keeps the *compressed* size, so streaming it under that length would
 * truncate the upload. When the length cannot be trusted (content-encoded, or absent) the body is
 * buffered in memory purely to measure it — large media is served uncompressed and takes the
 * zero-copy streaming path.
 */
export async function readSizedContent(response: Response): Promise<SizedContent> {
  const contentType = response.headers.get('content-type');

  if (!response.ok || isNonMediaContentType(contentType)) {
    const detail = await readBodyForDiagnostics(response);
    const location = response.headers.get('location');
    throw new Error(
      `Content download did not return media: status=${response.status} ` +
        `url=${response.url} contentType=${contentType ?? '<none>'} ` +
        `location=${location ?? '<none>'} body=${detail}`,
    );
  }

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

function isNonMediaContentType(contentType: string | null): boolean {
  if (contentType === null) {
    return false;
  }
  const base = contentType.split(';')[0]?.trim().toLowerCase() ?? '';
  return NON_MEDIA_CONTENT_TYPES.includes(base);
}

async function readBodyForDiagnostics(response: Response): Promise<string> {
  try {
    const text = await response.text();
    return text.length > DIAGNOSTIC_BODY_LIMIT
      ? `${text.slice(0, DIAGNOSTIC_BODY_LIMIT)}…(truncated)`
      : text;
  } catch {
    return '<unreadable body>';
  }
}
