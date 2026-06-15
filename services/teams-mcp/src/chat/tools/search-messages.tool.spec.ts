/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { UnauthorizedException } from '@nestjs/common';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// `@unique-ag/mcp-server-module` resolves to its built `dist`, which is not
// available when tests run without building workspace deps first (the service
// `build` is `nest build`, which does not build dependencies). Mock the `@Tool`
// decorator to a no-op so importing the tool never touches the real package.
vi.mock('@unique-ag/mcp-server-module', () => ({
  Tool: () => (_target: any, _key: string, _descriptor: PropertyDescriptor) => _descriptor,
}));

import type { SearchService } from '../search.service';
import { SearchMessagesInputSchema, SearchMessagesTool } from './search-messages.tool';

describe('SearchMessagesTool', () => {
  let searchService: SearchService;
  let tool: SearchMessagesTool;

  const traceService = { getSpan: () => undefined } as any;
  const context = {} as any;

  const validInput = SearchMessagesInputSchema.parse({ query: 'budget' });

  beforeEach(() => {
    searchService = {
      searchMessages: vi.fn().mockResolvedValue({
        messages: [],
        returnedCount: 0,
        moreResultsAvailable: false,
      }),
    } as any;
    tool = new SearchMessagesTool(traceService, searchService);
  });

  it('throws UnauthorizedException when the request is unauthenticated', async () => {
    await expect(
      tool.searchMessages(validInput, context, { user: undefined } as any),
    ).rejects.toThrow(UnauthorizedException);
    expect(searchService.searchMessages).not.toHaveBeenCalled();
  });

  it('delegates to SearchService with the resolved user profile id', async () => {
    const request = { user: { userProfileId: 'user-1' } } as any;

    const result = await tool.searchMessages(validInput, context, request);

    expect(searchService.searchMessages).toHaveBeenCalledWith(
      'user-1',
      expect.objectContaining({ query: 'budget', source: 'all', detail: 'summary' }),
    );
    expect(result).toEqual({ messages: [], returnedCount: 0, moreResultsAvailable: false });
  });

  describe('input schema refine', () => {
    it('rejects input with no search criterion', () => {
      const parsed = SearchMessagesInputSchema.safeParse({});
      expect(parsed.success).toBe(false);
    });

    it('accepts input with at least one criterion', () => {
      expect(SearchMessagesInputSchema.safeParse({ query: 'hi' }).success).toBe(true);
      expect(SearchMessagesInputSchema.safeParse({ hasAttachment: true }).success).toBe(true);
      expect(SearchMessagesInputSchema.safeParse({ isRead: false }).success).toBe(true);
    });
  });
});
