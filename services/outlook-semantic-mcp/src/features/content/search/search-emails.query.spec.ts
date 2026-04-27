import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MsGraphKqlSearchEmailsQuery } from './ms-graph-kql-search-emails.query';
import { SearchEmailsQuery } from './search-emails.query';
import {
  SearchBackend,
  SearchEmailResult,
  SemanticSearchEmailsQuery,
} from './semantic-search-emails.query';

function makeGraphResult(
  emailId: string,
  overrides?: Partial<SearchEmailResult>,
): SearchEmailResult {
  return {
    msGraphMessageId: emailId,
    emailId,
    folderId: 'folder-1',
    title: 'Graph Email',
    from: 'sender@example.com',
    outlookWebLink: 'https://outlook.com/msg/1',
    receivedDateTime: '2024-01-01T00:00:00Z',
    text: 'Graph body',
    uniqueContentUrl: undefined,
    backend: SearchBackend.MsGraph,
    ...overrides,
  };
}

function makeUniqueResult(
  emailId: string,
  overrides?: Partial<SearchEmailResult>,
): SearchEmailResult {
  return {
    uniqueContentId: `content-${emailId}`,
    emailId,
    folderId: 'folder-2',
    title: 'Unique Email',
    from: 'sender@example.com',
    outlookWebLink: 'https://outlook.com/msg/2',
    receivedDateTime: '2024-01-01T00:00:00Z',
    text: 'Unique body',
    uniqueContentUrl: 'https://unique.example.com/doc/1',
    backend: SearchBackend.Unique,
    ...overrides,
  };
}

describe('SearchEmailsQuery', () => {
  let semanticSearchQuery: { run: ReturnType<typeof vi.fn> };
  let msGraphKqlQuery: { run: ReturnType<typeof vi.fn> };
  let instance: SearchEmailsQuery;
  const originalMcpBackend = process.env.MCP_BACKEND;

  beforeEach(() => {
    semanticSearchQuery = { run: vi.fn() };
    msGraphKqlQuery = { run: vi.fn() };
    instance = new SearchEmailsQuery(
      semanticSearchQuery as unknown as SemanticSearchEmailsQuery,
      msGraphKqlQuery as unknown as MsGraphKqlSearchEmailsQuery,
    );
  });

  afterEach(() => {
    if (originalMcpBackend === undefined) {
      delete process.env.MCP_BACKEND;
    } else {
      process.env.MCP_BACKEND = originalMcpBackend;
    }
  });

  describe('MicrosoftGraph backend', () => {
    beforeEach(() => {
      process.env.MCP_BACKEND = 'MicrosoftGraph';
    });

    it('returns graph results and does not call the Unique backend', async () => {
      const graphA = makeGraphResult('email-1');
      const graphB = makeGraphResult('email-2');
      msGraphKqlQuery.run.mockResolvedValue([graphA, graphB]);

      const result = await instance.run('user-1', {
        msGraphSearchParams: { queries: [{ kqlQuery: 'subject:test' }] },
      });

      expect(result).toEqual([graphA, graphB]);
      expect(semanticSearchQuery.run).not.toHaveBeenCalled();
    });

    it('returns empty array when msGraphSearchParams is absent', async () => {
      const result = await instance.run('user-1', {});

      expect(result).toEqual([]);
      expect(msGraphKqlQuery.run).not.toHaveBeenCalled();
    });
  });

  describe('MicrosoftGraphAndUniqueApi backend', () => {
    beforeEach(() => {
      process.env.MCP_BACKEND = 'MicrosoftGraphAndUniqueApi';
    });

    it('places graph results first and appends unique-only results after', async () => {
      const graphA = makeGraphResult('email-graph-only');
      const graphShared = makeGraphResult('email-shared');
      const uniqueShared = makeUniqueResult('email-shared');
      const uniqueOnly = makeUniqueResult('email-unique-only');

      semanticSearchQuery.run.mockResolvedValue({ results: [uniqueShared, uniqueOnly] });
      msGraphKqlQuery.run.mockResolvedValue([graphA, graphShared]);

      const result = await instance.run('user-1', {
        semanticSearchParams: { search: 'test', conditions: [], limit: 10 },
        msGraphSearchParams: { queries: [{ kqlQuery: 'test' }] },
      });

      expect(result).toHaveLength(3);
      expect(result[0]).toEqual(graphA);
      expect(result[1]).toEqual(graphShared);
      expect(result[2]).toEqual(uniqueOnly);
    });

    it('drops unique result when its emailId overlaps with a graph result', async () => {
      const graphResult = makeGraphResult('email-shared');
      const uniqueDuplicate = makeUniqueResult('email-shared');

      semanticSearchQuery.run.mockResolvedValue({ results: [uniqueDuplicate] });
      msGraphKqlQuery.run.mockResolvedValue([graphResult]);

      const result = await instance.run('user-1', {
        semanticSearchParams: { search: 'test', conditions: [], limit: 10 },
        msGraphSearchParams: { queries: [{ kqlQuery: 'test' }] },
      });

      expect(result).toHaveLength(1);
      expect(result[0]).toEqual(graphResult);
    });

    it('returns empty array when both backends return no results', async () => {
      semanticSearchQuery.run.mockResolvedValue({ results: [] });
      msGraphKqlQuery.run.mockResolvedValue([]);

      const result = await instance.run('user-1', {
        semanticSearchParams: { search: 'test', conditions: [], limit: 10 },
        msGraphSearchParams: { queries: [{ kqlQuery: 'test' }] },
      });

      expect(result).toEqual([]);
    });

    it('skips the Unique backend when semanticSearchParams is absent', async () => {
      const graphA = makeGraphResult('email-1');
      msGraphKqlQuery.run.mockResolvedValue([graphA]);

      const result = await instance.run('user-1', {
        msGraphSearchParams: { queries: [{ kqlQuery: 'test' }] },
      });

      expect(result).toEqual([graphA]);
      expect(semanticSearchQuery.run).not.toHaveBeenCalled();
    });
  });
});
