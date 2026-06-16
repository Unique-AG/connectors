import { Injectable, Logger } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import pLimit from 'p-limit';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { type MsSearchHit, MsSearchResponseSchema } from './chat.dtos';
import { ChatService } from './chat.service';
import { type BuildSearchQueryParams, buildSearchQuery } from './utils/build-search-query';
import { normalizeContent } from './utils/normalize-content';

export type SearchSource = 'chat' | 'channel' | 'all';
export type SearchDetail = 'summary' | 'full';
export type SearchContentFormat = 'normalized' | 'raw';

export interface SearchMessagesParams extends BuildSearchQueryParams {
  source: SearchSource;
  detail: SearchDetail;
  contentFormat: SearchContentFormat;
  offset: number;
  size: number;
}

export interface SearchMessageRow {
  id: string;
  source: 'chat' | 'channel';
  chatId: string | null;
  teamId: string | null;
  channelId: string | null;
  senderDisplayName: string | null;
  summary: string | null;
  /** Hydrated message body; only present when `detail: 'full'` succeeds. */
  content?: string;
  createdDateTime: string | null;
  webUrl: string | null;
}

export interface SearchMessagesResult {
  messages: SearchMessageRow[];
  /** Count of rows on THIS page (after the source filter), not total matches. */
  returnedCount: number;
  moreResultsAvailable: boolean;
}

@Injectable()
export class SearchService {
  private readonly logger = new Logger(SearchService.name);

  // Single switch point for the Graph API version. The Microsoft Search API
  // ships chatMessage search on v1.0 (the client default). If a tenant rejects
  // it, flip this to 'beta' — the only change required.
  private static readonly GRAPH_API_VERSION = 'v1.0';

  // Hydration issues one Graph call per hit (N+1); cap concurrency to stay
  // throttle-friendly.
  private static readonly HYDRATION_CONCURRENCY = 5;

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly traceService: TraceService,
    private readonly chatService: ChatService,
  ) {}

  @Span()
  public async searchMessages(
    userProfileId: string,
    params: SearchMessagesParams,
  ): Promise<SearchMessagesResult> {
    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('source', params.source);
    span?.setAttribute('detail', params.detail);

    const queryString = buildSearchQuery(params);
    // The assembled KQL contains user free-text and identity filters
    // (from/to/mentions) and is treated as sensitive: it is never written to
    // spans or logs. Record only its length for debugging.
    span?.setAttribute('query_length', queryString.length);

    this.logger.debug(
      { userProfileId, queryLength: queryString.length, source: params.source },
      'Searching messages',
    );

    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const body = {
      requests: [
        {
          entityTypes: ['chatMessage'],
          query: { queryString },
          from: params.offset,
          size: params.size,
        },
      ],
    };

    const response = await client
      .api('/search/query')
      .version(SearchService.GRAPH_API_VERSION)
      .post(body);

    const parsed = MsSearchResponseSchema.parse(response);

    const containers = (parsed.value ?? []).flatMap((v) => v.hitsContainers ?? []);
    const hits = containers.flatMap((c) => c.hits ?? []);
    // moreResultsAvailable lives on the (first) container, not the hit.
    const moreResultsAvailable = containers[0]?.moreResultsAvailable ?? false;

    let rows = hits.map((hit) => this.mapHit(hit));

    // entityType is always chatMessage; the source split is derived from the
    // resource shape, so it can only be applied after the fetch. This shrinks
    // the page when filtering to a single source.
    if (params.source !== 'all') {
      rows = rows.filter((r) => r.source === params.source);
    }

    if (params.detail === 'full') {
      rows = await this.hydrate(userProfileId, rows, params.contentFormat);
    }

    span?.setAttribute('result_count', rows.length);

    return {
      messages: rows,
      returnedCount: rows.length,
      moreResultsAvailable,
    };
  }

  private mapHit(hit: MsSearchHit): SearchMessageRow {
    const resource = hit.resource;
    const channelId = resource?.channelIdentity?.channelId ?? null;
    const teamId = resource?.channelIdentity?.teamId ?? null;
    const chatId = resource?.chatId ?? null;

    let source: 'chat' | 'channel';
    if (channelId) {
      source = 'channel';
    } else if (chatId) {
      source = 'chat';
    } else {
      // Neither identifier present — Graph occasionally omits both. Default to
      // chat and note it; such a hit cannot be hydrated.
      source = 'chat';
      this.logger.debug({ hitId: hit.hitId }, 'Search hit missing chatId and channelIdentity');
    }

    const senderDisplayName =
      resource?.from?.user?.displayName ?? resource?.from?.application?.displayName ?? null;

    return {
      id: resource?.id ?? hit.hitId ?? '',
      source,
      chatId,
      teamId,
      channelId,
      senderDisplayName,
      summary: hit.summary ?? null,
      createdDateTime: resource?.createdDateTime ?? null,
      webUrl: resource?.webUrl ?? null,
    };
  }

  private async hydrate(
    userProfileId: string,
    rows: SearchMessageRow[],
    contentFormat: SearchContentFormat,
  ): Promise<SearchMessageRow[]> {
    const limit = pLimit(SearchService.HYDRATION_CONCURRENCY);

    return Promise.all(
      rows.map((row) =>
        limit(async () => {
          try {
            const message =
              row.source === 'channel' && row.teamId && row.channelId
                ? await this.chatService.getChannelMessageById(
                    userProfileId,
                    row.teamId,
                    row.channelId,
                    row.id,
                  )
                : row.source === 'chat' && row.chatId
                  ? await this.chatService.getChatMessageById(userProfileId, row.chatId, row.id)
                  : null;

            if (!message) {
              return row;
            }

            const content =
              contentFormat === 'normalized'
                ? normalizeContent(message.content, message.contentType, message.attachments)
                : message.content;

            return { ...row, content };
          } catch (error) {
            // A single deleted/forbidden message must not fail the page; fall
            // back to the summary-only row.
            this.logger.debug(
              { userProfileId, messageId: row.id, source: row.source, error },
              'Failed to hydrate search hit; falling back to summary',
            );
            return row;
          }
        }),
      ),
    );
  }
}
