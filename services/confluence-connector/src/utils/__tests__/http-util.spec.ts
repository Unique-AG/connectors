import type Dispatcher from 'undici/types/dispatcher';
import { describe, expect, it, vi } from 'vitest';
import { handleErrorStatus } from '../http-util';

function makeBody(text = ''): Dispatcher.BodyMixin {
  return {
    text: vi.fn().mockResolvedValue(text),
    json: vi.fn(),
    blob: vi.fn(),
    arrayBuffer: vi.fn(),
    formData: vi.fn(),
    bytes: vi.fn(),
    body: null,
    bodyUsed: false,
    dump: vi.fn(),
  } as unknown as Dispatcher.BodyMixin;
}

describe('handleErrorStatus', () => {
  it('does not throw for 200 OK', async () => {
    await expect(
      handleErrorStatus(200, makeBody(), 'https://example.com/api'),
    ).resolves.toBeUndefined();
  });

  it('does not throw for 201 Created', async () => {
    await expect(
      handleErrorStatus(201, makeBody(), 'https://example.com/api'),
    ).resolves.toBeUndefined();
  });

  it('does not throw for 204 No Content', async () => {
    await expect(
      handleErrorStatus(204, makeBody(), 'https://example.com/api'),
    ).resolves.toBeUndefined();
  });

  it('throws for 400 Bad Request', async () => {
    const body = makeBody('Bad input');

    await expect(handleErrorStatus(400, body, 'https://example.com/api')).rejects.toThrow(
      /Error response from https:\/\/example\.com\/api/,
    );
  });

  it('includes the status code in the error message', async () => {
    await expect(
      handleErrorStatus(403, makeBody('Forbidden'), 'https://example.com/api'),
    ).rejects.toThrow(/403/);
  });

  it('throws for 404 Not Found', async () => {
    await expect(
      handleErrorStatus(404, makeBody('Not Found'), 'https://example.com/resource'),
    ).rejects.toThrow(/Error response from/);
  });

  it('throws for 500 Internal Server Error', async () => {
    await expect(
      handleErrorStatus(500, makeBody('Server Error'), 'https://example.com/api'),
    ).rejects.toThrow(/500/);
  });

  it('includes response body text in the error message', async () => {
    await expect(
      handleErrorStatus(422, makeBody('Unprocessable entity'), 'https://example.com/api'),
    ).rejects.toThrow(/Unprocessable entity/);
  });

  it('falls back to "No response body" when body.text() rejects', async () => {
    const body = makeBody();
    vi.mocked(body.text).mockRejectedValueOnce(new Error('stream closed'));

    await expect(handleErrorStatus(503, body, 'https://example.com/api')).rejects.toThrow(
      /No response body/,
    );
  });

  it('does not throw for 299 (upper boundary of 2xx)', async () => {
    await expect(
      handleErrorStatus(299, makeBody(), 'https://example.com/api'),
    ).resolves.toBeUndefined();
  });

  it('throws for 300 (lower boundary outside 2xx)', async () => {
    await expect(
      handleErrorStatus(300, makeBody('Multiple Choices'), 'https://example.com/api'),
    ).rejects.toThrow(/300/);
  });
});
