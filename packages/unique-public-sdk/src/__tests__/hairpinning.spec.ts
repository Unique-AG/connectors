import { TestBed } from '@suites/unit';
import { TraceService } from 'nestjs-otel';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { UniqueContentService } from '../services/unique-content.service';
import { UNIQUE_PUBLIC_FETCH, UNIQUE_PUBLIC_SDK_OPTIONS } from '../unique-public-sdk.consts';

const context = describe;

const EXTERNAL_WRITE_URL =
  'https://account.blob.core.windows.net/container/blob?sv=2021&se=2024-01-01';
const INTERNAL_BASE = 'http://storage.internal:10000';
const INTERNAL_WRITE_URL = `${INTERNAL_BASE}/container/blob?sv=2021&se=2024-01-01`;

describe('Storage URL hairpinning', () => {
  const originalFetch = globalThis.fetch;

  function createService(storageInternalBaseUrl?: string) {
    return TestBed.solitary(UniqueContentService)
      .mock(UNIQUE_PUBLIC_FETCH)
      .impl(() => vi.fn())
      .mock(UNIQUE_PUBLIC_SDK_OPTIONS)
      .impl(() => ({
        apiBaseUrl: 'https://api.unique.app',
        apiVersion: '2023-12-06',
        serviceHeaders: {},
        retry: { maxAttempts: 3, baseDelayMs: 200, maxDelayMs: 10_000 },
        storageInternalBaseUrl,
      }))
      .mock(TraceService)
      .impl(() => ({ getSpan: () => null }))
      .compile();
  }

  beforeEach(() => {
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true });
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  context(`when storageInternalBaseUrl is "${INTERNAL_BASE}"`, () => {
    context(`and writeUrl is "${EXTERNAL_WRITE_URL}"`, () => {
      it('rewrites to the internal endpoint', async () => {
        const { unit: service } = await createService(INTERNAL_BASE);

        await service.uploadToStorage(EXTERNAL_WRITE_URL, new ReadableStream(), 'text/plain');

        expect(globalThis.fetch).toHaveBeenCalledWith(INTERNAL_WRITE_URL, expect.anything());
      });

      it('preserves the full path', async () => {
        const { unit: service } = await createService(INTERNAL_BASE);

        await service.uploadToStorage(EXTERNAL_WRITE_URL, new ReadableStream(), 'text/plain');

        expect(globalThis.fetch).toHaveBeenCalledWith(
          expect.stringContaining('/container/blob'),
          expect.anything(),
        );
      });

      it('preserves all query parameters', async () => {
        const { unit: service } = await createService(INTERNAL_BASE);

        await service.uploadToStorage(EXTERNAL_WRITE_URL, new ReadableStream(), 'text/plain');

        expect(globalThis.fetch).toHaveBeenCalledWith(INTERNAL_WRITE_URL, expect.anything());
      });

      it('changes the protocol to http', async () => {
        const { unit: service } = await createService(INTERNAL_BASE);

        await service.uploadToStorage(EXTERNAL_WRITE_URL, new ReadableStream(), 'text/plain');

        expect(globalThis.fetch).toHaveBeenCalledWith(
          expect.stringMatching(/^http:/),
          expect.anything(),
        );
      });
    });
  });

  context('when storageInternalBaseUrl is not set', () => {
    it('uses the original writeUrl unchanged', async () => {
      const { unit: service } = await createService(undefined);
      const writeUrl = 'https://account.blob.core.windows.net/container/blob';

      await service.uploadToStorage(writeUrl, new ReadableStream(), 'text/plain');

      expect(globalThis.fetch).toHaveBeenCalledWith(writeUrl, expect.anything());
    });
  });

  context('when writeUrl uses a non-standard port', () => {
    it('replaces the port with the internal endpoint port', async () => {
      const { unit: service } = await createService(INTERNAL_BASE);
      const writeUrl = 'https://account.blob.core.windows.net:8443/container/blob';

      await service.uploadToStorage(writeUrl, new ReadableStream(), 'text/plain');

      expect(globalThis.fetch).toHaveBeenCalledWith(
        `${INTERNAL_BASE}/container/blob`,
        expect.anything(),
      );
    });
  });
});
