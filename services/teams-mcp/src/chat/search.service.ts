import { Injectable, Logger } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import pLimit from 'p-limit';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { type MsSearchHit, MsSearchResponseSchema } from './chat.dtos';
import { ChatService } from './chat.service';
import { type BuildSearchQueryParams, buildSearchQuery } from './utils/build-search-query';
import { cleanSearchSummary } from './utils/clean-search-summary';
import { normalizeContent } from './utils/normalize-content';

export interface SearchMessagesParams extends BuildSearchQueryParams {
  offset: number;
  size: number;
}

export interface SearchMessageRow {
  id: string;
  source: 'chat' | 'channel' | 'unknown';
  chatId: string | null;
  teamId: string | null;
  channelId: string | null;
  senderDisplayName: string | null;
  summary: string | null;
  /** Hydrated message body; absent when the hit is unaddressable or the fetch failed. */
  content?: string;
  createdDateTime: string | null;
  webUrl: string | null;
}

export interface SearchMessagesResult {
  messages: SearchMessageRow[];
  /** Count of rows on THIS page, not total matches. */
  returnedCount: number;
  moreResultsAvailable: boolean;
}

interface MappedHit {
  row: SearchMessageRow;
  /**
   * Mailbox address of the sender. Used as the sender of last resort, only once
   * hydration has had its chance to supply a real display name.
   */
  senderAddress: string | null;
}

// An empty string is not a value. As an identifier it would classify a hit that
// cannot be addressed and build `/teams//channels//messages/{id}`; as a name or a
// timestamp it would satisfy `??` and shadow what hydration supplies. Treat it as
// absent everywhere.
function nonEmpty(value: string | null | undefined): string | null {
  return value || null;
}

function withoutContent(row: SearchMessageRow, senderAddress: string | null): SearchMessageRow {
  return { ...row, senderDisplayName: row.senderDisplayName ?? senderAddress };
}

// Rejects when `work` outlives `ms`. The request itself is left to finish on its
// own: the Graph client offers no cancellation, and the point is to stop the
// caller waiting, not to stop the request.
function withDeadline<T>(work: Promise<T>, ms: number): Promise<T> {
  let timer: NodeJS.Timeout | undefined;
  const expiry = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => reject(new Error(`Hydration exceeded ${ms}ms`)), ms);
  });

  return Promise.race([work, expiry]).finally(() => clearTimeout(timer));
}

@Injectable()
export class SearchService {
  private readonly logger = new Logger(SearchService.name);

  // Single switch point for the Graph API version. The Microsoft Search API
  // ships chatMessage search on v1.0 (the client default). If a tenant rejects
  // it, flip this to 'beta' — the only change required.
  private static readonly GRAPH_API_VERSION = 'v1.0';

  // Hydration issues one Graph call per hit (N+1). Graph throttles chat and
  // channel message reads at 1 request per second per container, so the cap is
  // deliberately low: hydration is unconditional now, and several hits from one
  // busy chat are the common case rather than the exception.
  private static readonly HYDRATION_CONCURRENCY = 3;

  // Hydration is unconditional, so a throttled page must not hold the whole
  // response hostage. The Graph client retries a 429 three times honouring
  // Retry-After, which can run into minutes; past this budget the remaining hits
  // give up their body rather than the caller giving up the page.
  private static readonly HYDRATION_BUDGET_MS = 15_000;

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly traceService: TraceService,
    private readonly chatService: ChatService,
  ) {}

  // NOTE: this is the one paginated Graph call site that does NOT use the shared
  // `PageIterator` helpers in `~/msgraph/graph-pagination`. The Microsoft Search
  // API (`POST /search/query`) does not page via `@odata.nextLink`; it pages via
  // `from`/`size` on the request and reports `moreResultsAvailable` on the
  // response. PageIterator only understands `@odata.nextLink`, so it cannot drive
  // this endpoint. The offset/size model is also the correct contract here — the
  // MCP client paginates explicitly via `offset` + `moreResultsAvailable`, which
  // is always surfaced (never silently capped). The per-page size bound is a
  // product choice made in the search tool, not a Graph limit.
  @Span()
  public async searchMessages(
    userProfileId: string,
    params: SearchMessagesParams,
  ): Promise<SearchMessagesResult> {
    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);

    const queryString = buildSearchQuery(params);
    // The assembled KQL contains user free-text and identity filters
    // (from/to/mentions) and is treated as sensitive: it is never written to
    // spans or logs. Record only its length for debugging.
    span?.setAttribute('query_length', queryString.length);

    this.logger.debug({ userProfileId, queryLength: queryString.length }, 'Searching messages');

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

    const rows = await this.hydrate(
      userProfileId,
      hits.map((hit) => this.mapHit(hit)),
    );

    span?.setAttribute('result_count', rows.length);

    return {
      messages: rows,
      returnedCount: rows.length,
      moreResultsAvailable,
    };
  }

  // Container classification uses only what Microsoft documents on a chatMessage:
  // `channelIdentity.teamId` + `.channelId` for a channel message, `chatId` for a
  // chat message. A chat hit arrives with `channelIdentity: {}`, so the object's
  // presence proves nothing — only both ids do. A hit matching neither shape is
  // reported as 'unknown' rather than guessed at.
  private mapHit(hit: MsSearchHit): MappedHit {
    const resource = hit.resource;
    const teamId = nonEmpty(resource?.channelIdentity?.teamId);
    const channelId = nonEmpty(resource?.channelIdentity?.channelId);
    const chatId = nonEmpty(resource?.chatId);

    const isChannel = teamId !== null && channelId !== null;
    const source = isChannel ? 'channel' : chatId !== null ? 'chat' : 'unknown';

    const from = resource?.from;
    // A search hit is an Exchange projection, so the mailbox sender is the one
    // actually populated; the Teams identity set is read as a fallback for
    // tenants that return it. The bare address is deliberately NOT part of this
    // chain — it is a last resort applied after hydration, so a fetched display
    // name always beats an email address.
    const senderDisplayName =
      nonEmpty(from?.emailAddress?.name) ??
      nonEmpty(from?.user?.displayName) ??
      nonEmpty(from?.application?.displayName);

    return {
      row: {
        id: nonEmpty(resource?.id) ?? nonEmpty(hit.hitId) ?? '',
        source,
        // The ids a row carries describe the container it reports, so a hit that
        // proves a channel does not also hand back a chat id to follow.
        chatId: isChannel ? null : chatId,
        teamId: isChannel ? teamId : null,
        channelId: isChannel ? channelId : null,
        senderDisplayName,
        summary: cleanSearchSummary(hit.summary),
        createdDateTime: nonEmpty(resource?.createdDateTime),
        // The retrievable-property list names `webUrl` (a Teams deep link); the
        // documented example payloads carry `webLink` (an Outlook Web URL)
        // instead, so this field may hold either kind of link.
        webUrl: resource?.webUrl ?? resource?.webLink ?? null,
      },
      senderAddress: nonEmpty(from?.emailAddress?.address),
    };
  }

  private async hydrate(userProfileId: string, hits: MappedHit[]): Promise<SearchMessageRow[]> {
    const limit = pLimit(SearchService.HYDRATION_CONCURRENCY);
    const deadline = Date.now() + SearchService.HYDRATION_BUDGET_MS;

    return Promise.all(
      hits.map(({ row, senderAddress }) =>
        limit(async () => {
          const { teamId, channelId, chatId } = row;
          // A hit is fetched by the ids it carries: a message id, plus either
          // both channel ids or a chat id. A hit missing any of those cannot be
          // addressed in Graph at all, so no call is attempted for it.
          const fetchMessage =
            row.id === ''
              ? null
              : teamId !== null && channelId !== null
                ? () =>
                    this.chatService.getChannelMessageById(userProfileId, teamId, channelId, row.id)
                : chatId !== null
                  ? () => this.chatService.getChatMessageById(userProfileId, chatId, row.id)
                  : null;

          if (!fetchMessage) {
            // Shape only — never ids, never content.
            this.logger.debug(
              {
                userProfileId,
                source: row.source,
                hasMessageId: row.id !== '',
                hasChatId: chatId !== null,
                hasTeamId: teamId !== null,
                hasChannelId: channelId !== null,
              },
              'Search hit is not addressable in Graph; returning it without content',
            );
            return withoutContent(row, senderAddress);
          }

          const remaining = deadline - Date.now();
          if (remaining <= 0) {
            this.logger.warn(
              { userProfileId, source: row.source },
              'Hydration budget spent before this hit; returning it without content',
            );
            return withoutContent(row, senderAddress);
          }

          try {
            const message = await withDeadline(fetchMessage(), remaining);

            const content = normalizeContent(
              message.content,
              message.contentType,
              message.attachments,
              message.deletedDateTime,
            );

            // Hydration only ever fills a gap, so a row reads the same whether
            // or not its body could be fetched. `webUrl` is not merged at all:
            // chatmessage-get returns null for chat messages and would blank the
            // link the hit itself provided.
            return {
              ...row,
              senderDisplayName:
                row.senderDisplayName ?? message.senderDisplayName ?? senderAddress,
              createdDateTime: row.createdDateTime ?? message.createdDateTime,
              content,
            };
          } catch (error) {
            // A single deleted/forbidden message must not fail the page; fall
            // back to the summary-only row. Logged at warn: hydration is
            // unconditional now, so a tenant that never granted admin consent
            // for channel messages fails every channel hit, and that must be
            // visible without turning on debug logging.
            this.logger.warn(
              { userProfileId, messageId: row.id, source: row.source, error },
              'Failed to hydrate search hit; falling back to summary',
            );
            return withoutContent(row, senderAddress);
          }
        }),
      ),
    );
  }
}
