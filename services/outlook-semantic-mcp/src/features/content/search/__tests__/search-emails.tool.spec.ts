import { McpModule } from '@unique-ag/mcp-server-module';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import type { INestApplication } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import type { NextFunction, Request, Response } from 'express';
import { OpenTelemetryModule } from 'nestjs-otel';
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest';
import { GetSubscriptionStatusQuery } from '~/features/subscriptions/get-subscription-status.query';
import { GetFullSyncStatsQuery } from '~/features/sync/full-sync/get-full-sync-stats.query';
import { FetchNextSearchPagesTool } from '../fetch-next-search-pages.tool';
import { SearchEmailsQuery } from '../search-emails.query';
import { SearchEmailsTool } from '../search-emails.tool';
import {
  SearchBackend,
  type SearchEmailResult,
  type SearchPage,
  SearchPageStatus,
} from '../search-results.types';

vi.mock('~/utils/backend-config.utils', () => ({ isMicrosoftGraphBackend: () => true }));

const WEB_LINK =
  'https://outlook.office365.com/owa/?ItemID=AAMk1&exvsurl=1&viewmodel=ReadMessageItem';

const email = (overrides: Partial<SearchEmailResult>): SearchEmailResult => ({
  msGraphMessageId: 'msg-1',
  folderId: 'folder-1',
  title: 'Budget Q3',
  from: 'alex@example.com',
  sourceMailbox: 'own@example.com',
  outlookWebLink: WEB_LINK,
  receivedDateTime: '2026-08-25T09:00:00Z',
  isDraft: false,
  text: '## Preview\nNumbers for the quarter.',
  uniqueContentUrl: undefined,
  backend: SearchBackend.MsGraph,
  openEmailParams: { id: 'msg-1' },
  replyToParams: { inReplyToMessageId: 'msg-1', isReplyable: true },
  ...overrides,
});

const PAGES: SearchPage[] = [
  {
    backend: SearchBackend.MsGraph,
    query: 'budget',
    mailbox: 'own@example.com',
    status: SearchPageStatus.HasMore,
    cursorId: 'cursor-2',
  },
];

describe('search_emails and fetch_next_search_pages over MCP', () => {
  let app: INestApplication;
  let client: Client;
  let searchEmailsQuery: { run: Mock; fetchNextPages: Mock };

  beforeEach(async () => {
    searchEmailsQuery = { run: vi.fn(), fetchNextPages: vi.fn() };
    const moduleRef = await Test.createTestingModule({
      imports: [
        OpenTelemetryModule.forRoot(),
        McpModule.forRoot({
          name: 'outlook-semantic-mcp',
          version: '1.0.0',
          streamableHttp: { enableJsonResponse: true, statelessMode: false },
        }),
      ],
      providers: [
        SearchEmailsTool,
        FetchNextSearchPagesTool,
        { provide: SearchEmailsQuery, useValue: searchEmailsQuery },
        { provide: GetSubscriptionStatusQuery, useValue: { run: vi.fn() } },
        { provide: GetFullSyncStatsQuery, useValue: { run: vi.fn() } },
      ],
    }).compile();

    app = moduleRef.createNestApplication({ logger: false });
    app.use((req: Request, _res: Response, next: NextFunction) => {
      Object.assign(req, { user: { userProfileId: 'user_profile_01kqcg8m7teh6sh8tehd2k0byb' } });
      next();
    });
    await app.listen(0, '127.0.0.1');

    client = new Client({ name: 'test-client', version: '1.0.0' });
    await client.connect(new StreamableHTTPClientTransport(new URL(`${await app.getUrl()}/mcp`)));
    // Caches the output schemas, so callTool checks structuredContent against them.
    await client.listTools();
  });

  afterEach(async () => {
    await client.close();
    await app.close();
  });

  it('sends the emails under results with the paging beside them as one JSON text item', async () => {
    const own = email({});
    searchEmailsQuery.fetchNextPages.mockResolvedValue({
      results: [own],
      pages: PAGES,
      hasMore: true,
      searchSummary: undefined,
    });

    const result = await client.callTool({
      name: 'fetch_next_search_pages',
      arguments: { cursorIds: ['cursor-1'] },
    });

    const output = { success: true, results: [own], hasMore: true, pages: PAGES };
    expect(result.structuredContent).toEqual(output);
    expect(result.content).toEqual([{ type: 'text', text: JSON.stringify(output) }]);
  });

  it('returns a search without results as one text item', async () => {
    searchEmailsQuery.run.mockResolvedValue({
      results: [],
      pages: [],
      hasMore: false,
      searchSummary: 'No mailbox matched.',
    });

    const result = await client.callTool({
      name: 'search_emails',
      arguments: { msGraphKeywordSearchQueries: [{ kqlQuery: 'budget' }] },
    });

    const output = {
      success: true,
      results: [],
      hasMore: false,
      pages: [],
      searchNotes: 'No mailbox matched.',
    };
    expect(result.structuredContent).toEqual(output);
    expect(result.content).toEqual([{ type: 'text', text: JSON.stringify(output) }]);
  });
});
