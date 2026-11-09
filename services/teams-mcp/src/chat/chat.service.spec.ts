import type { Client, PageCollection } from '@microsoft/microsoft-graph-client';
import type { TraceService } from 'nestjs-otel';
import { describe, expect, it, type Mock, vi } from 'vitest';
import type { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { LAST_MESSAGE_PREVIEW_MAX_LENGTH } from './chat.dtos';
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
  api: Mock;
  top: Mock;
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

describe('ChatService listChats lastMessagePreview', () => {
  async function previewFor(lastMessagePreview: unknown): Promise<string | null> {
    const [chat] = makeChats('a', 1);
    const { service } = makeService(makePage([{ ...chat, lastMessagePreview }]));
    const [mapped] = await service.listChats('user-profile-1');
    return mapped?.lastMessagePreview ?? null;
  }

  it('flattens Teams HTML to text, keeping mention names and decoding entities', async () => {
    const preview = await previewFor({
      createdDateTime: '2026-06-01T00:00:00Z',
      isDeleted: false,
      body: {
        contentType: 'html',
        content: '<p><at id="0">Alice</at>&nbsp;the Q3 deck &amp; notes&#39;re   ready</p>',
      },
    });

    expect(preview).toBe("Alice the Q3 deck & notes're ready");
  });

  it('separates block elements without splitting inline formatting', async () => {
    const preview = await previewFor({
      body: {
        contentType: 'html',
        content:
          '<p>Hel<b>lo</b> team</p><p>see <a href="https://contoso.test/doc">the doc</a></p>',
      },
    });

    expect(preview).toBe('Hello team see the doc');
  });

  it('keeps an emoji as its alt text', async () => {
    const preview = await previewFor({
      body: {
        contentType: 'html',
        content: '<p>Nice <emoji id="smile" alt="😄" title="Smile"></emoji> work</p>',
      },
    });

    expect(preview).toBe('Nice 😄 work');
  });

  it('passes a text body through with whitespace collapsed', async () => {
    const preview = await previewFor({
      body: { contentType: 'text', content: '  See you\n tomorrow  ' },
    });

    expect(preview).toBe('See you tomorrow');
  });

  it('cuts a long message to the preview length, ellipsis included', async () => {
    const preview = await previewFor({
      body: { contentType: 'text', content: 'a'.repeat(LAST_MESSAGE_PREVIEW_MAX_LENGTH + 50) },
    });

    expect(preview).toBe(`${'a'.repeat(LAST_MESSAGE_PREVIEW_MAX_LENGTH - 1)}…`);
  });

  it('keeps an emoji whole when it sits at the preview length', async () => {
    const lead = 'a'.repeat(LAST_MESSAGE_PREVIEW_MAX_LENGTH - 2);
    const preview = await previewFor({
      body: { contentType: 'text', content: `${lead}😄 and more` },
    });

    expect(preview).toBe(`${lead}😄…`);
  });

  it('drops text nested too deep to walk, rather than failing the list', async () => {
    const depth = 20_000;
    const preview = await previewFor({
      body: {
        contentType: 'html',
        content: `<p>Hi team ${'<span>'.repeat(depth)}buried${'</span>'.repeat(depth)}</p>`,
      },
    });

    expect(preview).toBe('Hi team');
  });

  it('returns null for a deleted last message', async () => {
    const preview = await previewFor({
      isDeleted: true,
      body: { contentType: 'text', content: 'gone' },
    });

    expect(preview).toBeNull();
  });

  it('returns null when the last message has no text, such as a system event or an attachment', async () => {
    const systemEvent = await previewFor({
      body: { contentType: 'html', content: '<systemEventMessage/>' },
    });
    const attachmentOnly = await previewFor({
      body: { contentType: 'html', content: '<attachment id="abc"></attachment>' },
    });

    expect(systemEvent).toBeNull();
    expect(attachmentOnly).toBeNull();
  });

  it('returns null when Graph sends no body', async () => {
    const preview = await previewFor({ createdDateTime: '2026-06-01T00:00:00Z' });

    expect(preview).toBeNull();
  });
});
