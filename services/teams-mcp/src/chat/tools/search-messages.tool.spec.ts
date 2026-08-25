import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context } from '@unique-ag/mcp-server-module';
import { TestBed } from '@suites/unit';
import { TraceService } from 'nestjs-otel';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SearchService } from '../search.service';
import { SearchMessagesInputSchema, SearchMessagesTool } from './search-messages.tool';

describe('SearchMessagesInputSchema', () => {
  it('applies the defaults for offset and page size', () => {
    const parsed = SearchMessagesInputSchema.parse({ query: 'deploy' });

    expect(parsed).toMatchObject({ offset: 0, size: 25 });
  });

  it('accepts a page size below the maximum', () => {
    expect(SearchMessagesInputSchema.parse({ query: 'deploy', size: 5 }).size).toBe(5);
  });

  it('rejects a page size above 25', () => {
    const result = SearchMessagesInputSchema.safeParse({ query: 'deploy', size: 50 });

    expect(result.success).toBe(false);
  });

  it('drops the container and detail parameters an older client still sends', () => {
    const parsed = SearchMessagesInputSchema.parse({
      query: 'deploy',
      source: 'channel',
      detail: 'full',
    });

    expect(parsed).not.toHaveProperty('source');
    expect(parsed).not.toHaveProperty('detail');
  });

  it('rejects a search with no criterion', () => {
    expect(SearchMessagesInputSchema.safeParse({}).success).toBe(false);
  });
});

describe('SearchMessagesTool', () => {
  let unit: SearchMessagesTool;
  let searchMessages: ReturnType<typeof vi.fn>;

  const request = { user: { userProfileId: 'user-profile-1' } } as McpAuthenticatedRequest;
  const context = {} as Context;

  beforeEach(async () => {
    searchMessages = vi
      .fn()
      .mockResolvedValue({ messages: [], returnedCount: 0, moreResultsAvailable: false });

    ({ unit } = await TestBed.solitary(SearchMessagesTool)
      .mock(TraceService)
      .impl(() => ({ getSpan: () => undefined }))
      .mock(SearchService)
      .impl(() => ({ searchMessages }))
      .compile());
  });

  it('passes the parsed pagination through to the search service', async () => {
    const input = SearchMessagesInputSchema.parse({ query: 'deploy', offset: 25, size: 10 });

    await unit.searchMessages(input, context, request);

    expect(searchMessages).toHaveBeenCalledWith(
      'user-profile-1',
      expect.objectContaining({
        query: 'deploy',
        offset: 25,
        size: 10,
      }),
    );
  });

  it('rejects a request that carries no authenticated user', async () => {
    const input = SearchMessagesInputSchema.parse({ query: 'deploy' });

    await expect(
      unit.searchMessages(input, context, {} as McpAuthenticatedRequest),
    ).rejects.toThrow('User not authenticated');
  });
});
