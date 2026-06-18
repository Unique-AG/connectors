import { describe, expect, it, vi } from 'vitest';
import { z } from 'zod';
import { fetchAllPaginated } from '../confluence-fetch-paginated';

const BASE_URL = 'https://confluence.example.com';

const itemSchema = z.object({ id: z.string(), name: z.string() });
type Item = z.infer<typeof itemSchema>;

function makeResponse(items: Item[], nextPath?: string) {
  return {
    results: items,
    _links: { next: nextPath },
  };
}

describe('fetchAllPaginated', () => {
  it('returns all results from a single-page response', async () => {
    const httpGet = vi.fn().mockResolvedValueOnce(
      makeResponse([
        { id: '1', name: 'Page A' },
        { id: '2', name: 'Page B' },
      ]),
    );

    const result = await fetchAllPaginated('/api/items', BASE_URL, httpGet, itemSchema);

    expect(result).toEqual([
      { id: '1', name: 'Page A' },
      { id: '2', name: 'Page B' },
    ]);
    expect(httpGet).toHaveBeenCalledTimes(1);
    expect(httpGet).toHaveBeenCalledWith('/api/items');
  });

  it('follows _links.next to fetch subsequent pages', async () => {
    const httpGet = vi
      .fn()
      .mockResolvedValueOnce(makeResponse([{ id: '1', name: 'Page A' }], '/api/items?cursor=p2'))
      .mockResolvedValueOnce(makeResponse([{ id: '2', name: 'Page B' }], '/api/items?cursor=p3'))
      .mockResolvedValueOnce(makeResponse([{ id: '3', name: 'Page C' }]));

    const result = await fetchAllPaginated('/api/items', BASE_URL, httpGet, itemSchema);

    expect(result).toEqual([
      { id: '1', name: 'Page A' },
      { id: '2', name: 'Page B' },
      { id: '3', name: 'Page C' },
    ]);
    expect(httpGet).toHaveBeenCalledTimes(3);
    expect(httpGet).toHaveBeenNthCalledWith(1, '/api/items');
    expect(httpGet).toHaveBeenNthCalledWith(2, `${BASE_URL}/api/items?cursor=p2`);
    expect(httpGet).toHaveBeenNthCalledWith(3, `${BASE_URL}/api/items?cursor=p3`);
  });

  it('returns an empty array when the response has no results', async () => {
    const httpGet = vi.fn().mockResolvedValueOnce(makeResponse([]));

    const result = await fetchAllPaginated('/api/items', BASE_URL, httpGet, itemSchema);

    expect(result).toEqual([]);
    expect(httpGet).toHaveBeenCalledTimes(1);
  });

  it('stops pagination when _links.next is absent', async () => {
    const httpGet = vi
      .fn()
      .mockResolvedValueOnce(makeResponse([{ id: '1', name: 'Page A' }]))
      .mockResolvedValueOnce(makeResponse([{ id: '2', name: 'Page B' }]));

    await fetchAllPaginated('/api/items', BASE_URL, httpGet, itemSchema);

    expect(httpGet).toHaveBeenCalledTimes(1);
  });

  it('prefixes next URL with baseUrl', async () => {
    const httpGet = vi
      .fn()
      .mockResolvedValueOnce(makeResponse([{ id: '1', name: 'A' }], '/wiki/rest/api/next'))
      .mockResolvedValueOnce(makeResponse([]));

    await fetchAllPaginated('/wiki/rest/api/items', BASE_URL, httpGet, itemSchema);

    expect(httpGet).toHaveBeenNthCalledWith(2, `${BASE_URL}/wiki/rest/api/next`);
  });

  it('throws when the response does not match the schema', async () => {
    const httpGet = vi.fn().mockResolvedValueOnce({ results: [{ bad: 'shape' }], _links: {} });

    await expect(fetchAllPaginated('/api/items', BASE_URL, httpGet, itemSchema)).rejects.toThrow();
  });
});
