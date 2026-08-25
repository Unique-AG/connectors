import type { Client, PageCollection } from '@microsoft/microsoft-graph-client';
import type { TraceService } from 'nestjs-otel';
import { describe, expect, it, vi } from 'vitest';
import type { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { ChatService, GRAPH_CHATS_PAGE_LIMIT } from './chat.service';

function makeChats(prefix: string, count: number): Record<string, unknown>[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `19:${prefix}-${index}@unq.gbl.spaces`,
    chatType: 'oneOnOne',
    topic: null,
    createdDateTime: '2026-01-01T00:00:00Z',
    lastMessagePreview: { createdDateTime: '2026-06-01T00:00:00Z' },
    members: [{ userId: 'user-1', displayName: 'Alice Smith', email: 'alice@contoso.com' }],
  }));
}

function makePage(value: Record<string, unknown>[], nextLink?: string): PageCollection {
  return { value, ...(nextLink ? { '@odata.nextLink': nextLink } : {}) };
}

function makeService(page: PageCollection): {
  service: ChatService;
  api: ReturnType<typeof vi.fn>;
  top: ReturnType<typeof vi.fn>;
} {
  const top = vi.fn();
  const api = vi.fn(() => {
    const builder = {
      expand: () => builder,
      top: (value: number) => {
        top(value);
        return builder;
      },
      orderby: () => builder,
      get: async () => page,
    };
    return builder;
  });

  const graphClientFactory = {
    createClientForUser: vi.fn().mockReturnValue({ api } as unknown as Client),
  } as unknown as GraphClientFactory;
  const traceService = { getSpan: vi.fn().mockReturnValue(undefined) } as unknown as TraceService;

  return { service: new ChatService(graphClientFactory, traceService), api, top };
}

describe('ChatService listChats', () => {
  it('returns the chats Graph serves in the page', async () => {
    const { service } = makeService(makePage(makeChats('a', GRAPH_CHATS_PAGE_LIMIT)));

    const chats = await service.listChats('user-profile-1', GRAPH_CHATS_PAGE_LIMIT);

    expect(chats).toHaveLength(GRAPH_CHATS_PAGE_LIMIT);
  });

  it('asks Graph for the caller-requested page size', async () => {
    const { service, top } = makeService(makePage(makeChats('a', 5)));

    await service.listChats('user-profile-1', 5);

    expect(top).toHaveBeenCalledWith(5);
  });

  it('defaults to the Graph page size when the caller passes none', async () => {
    const { service, top } = makeService(makePage(makeChats('a', 3)));

    await service.listChats('user-profile-1');

    expect(top).toHaveBeenCalledWith(GRAPH_CHATS_PAGE_LIMIT);
  });

  // `limit` is a page size, so one call is one Graph request even when Graph
  // offers a next page.
  it('does not follow the next page', async () => {
    const { service, api } = makeService(
      makePage(makeChats('a', GRAPH_CHATS_PAGE_LIMIT), 'https://graph.test/chats-page-2'),
    );

    await service.listChats('user-profile-1', GRAPH_CHATS_PAGE_LIMIT);

    expect(api).toHaveBeenCalledTimes(1);
  });

  it('maps the Graph chat shape onto lastMessageAt', async () => {
    const { service } = makeService(makePage(makeChats('a', 1)));

    const chats = await service.listChats('user-profile-1', GRAPH_CHATS_PAGE_LIMIT);

    expect(chats[0]).toMatchObject({
      chatType: 'oneOnOne',
      lastMessageAt: '2026-06-01T00:00:00Z',
    });
  });
});
