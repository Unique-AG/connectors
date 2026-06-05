import { describe, expect, it } from 'vitest';
import { readSizedContent } from './sized-content';

async function collect(stream: ReadableStream<Uint8Array>): Promise<Uint8Array> {
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

describe('readSizedContent', () => {
  it('streams an identity-encoded response using the advertised content-length', async () => {
    const body = new Uint8Array(20_000).fill(7);
    const response = new Response(body, {
      status: 200,
      headers: { 'content-type': 'video/mp4', 'content-length': String(body.byteLength) },
    });

    const { stream, size } = await readSizedContent(response);

    expect(size).toBe(20_000);
    expect((await collect(stream)).byteLength).toBe(20_000);
  });

  it('buffers to measure the decompressed size when the body is content-encoded', async () => {
    // gzip body whose content-length header (compressed) must NOT be trusted as the stream size.
    const decompressed = new TextEncoder().encode('WEBVTT\n\n'.repeat(500));
    const response = new Response(decompressed, {
      status: 200,
      headers: {
        'content-type': 'text/vtt',
        'content-encoding': 'gzip',
        'content-length': '120',
      },
    });

    const { stream, size } = await readSizedContent(response);

    expect(size).toBe(decompressed.byteLength);
    expect((await collect(stream)).byteLength).toBe(decompressed.byteLength);
  });

  it('throws (instead of uploading) when the download is not OK, surfacing the body', async () => {
    const response = new Response('<Error><Code>AuthenticationFailed</Code></Error>', {
      status: 403,
      headers: { 'content-type': 'application/xml' },
    });

    await expect(readSizedContent(response)).rejects.toThrow(/status=403.*AuthenticationFailed/s);
  });

  it('throws when a 200 returns a non-media (JSON error) body rather than the content', async () => {
    const response = new Response(JSON.stringify({ error: { code: 'NotFound' } }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });

    await expect(readSizedContent(response)).rejects.toThrow(
      /contentType=application\/json.*NotFound/s,
    );
  });
});
