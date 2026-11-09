import { Injectable, Logger } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import pLimit from 'p-limit';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { ChannelService } from './channel.service';
import {
  type MsChat,
  type MsChatMessage,
  type MsSearchHit,
  MsSearchResponseSchema,
} from './chat.dtos';
import { ChatService } from './chat.service';
import { type BuildSearchQueryParams, buildSearchQuery } from './utils/build-search-query';

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
  /** The chat topic, or its members' names when it has none. Null when the lookup failed. */
  chatName: string | null;
  teamName: string | null;
  channelName: string | null;
  senderDisplayName: string | null;
  summary: string | null;
  /**
   * The message as Graph returns it, fetched per hit. Absent when the hit names
   * no container or the fetch failed. The body is passed through untouched.
   */
  message?: MsChatMessage;
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

// An empty string is not a value. As an id it builds `/teams//channels//messages`.
// As a name or a timestamp it satisfies `??` and hides what hydration supplies.
function nonEmpty(value: string | null | undefined): string | null {
  return value || null;
}

interface ContainerNames {
  chats: Map<string, string | null>;
  teams: Map<string, string>;
  channels: Map<string, string | null>;
}

function channelKey(teamId: string, channelId: string): string {
  return `${teamId}/${channelId}`;
}

function chatName(chat: MsChat): string | null {
  if (chat.topic) {
    return chat.topic;
  }
  const memberNames = chat.members.flatMap((member) =>
    member.displayName ? [member.displayName] : [],
  );
  return memberNames.length > 0 ? memberNames.join(', ') : null;
}

function withoutContent(row: SearchMessageRow, senderAddress: string | null): SearchMessageRow {
  return { ...row, senderDisplayName: row.senderDisplayName ?? senderAddress };
}

// Rejects when `work` outlives `ms`. The request is left to finish on its own:
// the Graph client cannot cancel, and the point is to stop the caller waiting.
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

  // One Graph call per hit. Graph throttles reads of one chat or channel at about
  // 1 per second, and several hits from one busy chat are common, so keep this low.
  private static readonly HYDRATION_CONCURRENCY = 3;

  // The client retries a 429 and honours Retry-After, which can take minutes.
  // Past this budget a hit gives up its body, so the caller still gets the page.
  // Container names run alongside hydration and share the same budget.
  private static readonly HYDRATION_BUDGET_MS = 15_000;

  private static readonly NAME_LOOKUP_CONCURRENCY = 3;

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly traceService: TraceService,
    private readonly chatService: ChatService,
    private readonly channelService: ChannelService,
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

    const mappedHits = hits.map((hit) => this.mapHit(hit));
    const [hydratedRows, names] = await Promise.all([
      this.hydrate(userProfileId, mappedHits),
      this.lookUpContainerNames(
        userProfileId,
        mappedHits.map(({ row }) => row),
      ),
    ]);
    const rows = hydratedRows.map((row) => this.withContainerNames(row, names));

    span?.setAttribute('result_count', rows.length);

    return {
      messages: rows,
      returnedCount: rows.length,
      moreResultsAvailable,
    };
  }

  // Classification uses only documented fields: both `channelIdentity` ids mean a
  // channel, `chatId` means a chat. A chat hit arrives with `channelIdentity: {}`,
  // so the object proves nothing. Only the two ids do. Anything else is 'unknown'.
  private mapHit(hit: MsSearchHit): MappedHit {
    const resource = hit.resource;
    const teamId = nonEmpty(resource?.channelIdentity?.teamId);
    const channelId = nonEmpty(resource?.channelIdentity?.channelId);
    const chatId = nonEmpty(resource?.chatId);

    const isChannel = teamId !== null && channelId !== null;
    const source = isChannel ? 'channel' : chatId !== null ? 'chat' : 'unknown';

    const from = resource?.from;
    // A hit is an Exchange copy, so the mailbox sender is the one Graph fills in.
    // The Teams identity set is a fallback. The bare address is not in this chain:
    // it is used after hydration, so a fetched name always beats an address.
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
        chatName: null,
        teamName: null,
        channelName: null,
        senderDisplayName,
        summary: hit.summary ?? null,
        createdDateTime: nonEmpty(resource?.createdDateTime),
        // The retrievable-property list names `webUrl` (a Teams deep link); the
        // documented example payloads carry `webLink` (an Outlook Web URL)
        // instead, so this field may hold either kind of link.
        webUrl: resource?.webUrl ?? resource?.webLink ?? null,
      },
      senderAddress: nonEmpty(from?.emailAddress?.address),
    };
  }

  // One lookup per distinct chat and channel, plus one joinedTeams call for every
  // team name at once. A name that cannot be fetched stays null and never fails
  // the page, the same as a hit whose body cannot be fetched.
  private async lookUpContainerNames(
    userProfileId: string,
    rows: SearchMessageRow[],
  ): Promise<ContainerNames> {
    const chatIds = new Set(rows.flatMap(({ chatId }) => (chatId ? [chatId] : [])));
    const channels = new Map(
      rows.flatMap(({ teamId, channelId }) =>
        teamId && channelId
          ? [[channelKey(teamId, channelId), { teamId, channelId }] as const]
          : [],
      ),
    );

    const limit = pLimit(SearchService.NAME_LOOKUP_CONCURRENCY);
    const deadline = Date.now() + SearchService.HYDRATION_BUDGET_MS;
    const lookUp = <T>(container: string, work: () => Promise<T>): Promise<T | null> =>
      limit(async () => {
        const remaining = deadline - Date.now();
        if (remaining <= 0) {
          return null;
        }
        return withDeadline(work(), remaining);
      }).catch((error: unknown) => {
        this.logger.warn(
          { userProfileId, container, error },
          'Failed to look up a search hit container name; leaving it null',
        );
        return null;
      });

    const [chatEntries, channelEntries, teams] = await Promise.all([
      Promise.all(
        [...chatIds].map(
          async (chatId) =>
            [
              chatId,
              await lookUp('chat', () => this.chatService.getChat(userProfileId, chatId)),
            ] as const,
        ),
      ),
      Promise.all(
        [...channels].map(
          async ([key, { teamId, channelId }]) =>
            [
              key,
              await lookUp('channel', () =>
                this.channelService.getChannel(userProfileId, teamId, channelId),
              ),
            ] as const,
        ),
      ),
      channels.size > 0
        ? lookUp('team', () => this.channelService.listTeams(userProfileId))
        : Promise.resolve(null),
    ]);

    return {
      chats: new Map(chatEntries.map(([chatId, chat]) => [chatId, chat ? chatName(chat) : null])),
      teams: new Map((teams ?? []).map((team) => [team.id, team.displayName])),
      channels: new Map(
        channelEntries.map(([key, channel]) => [key, channel?.displayName ?? null]),
      ),
    };
  }

  private withContainerNames(row: SearchMessageRow, names: ContainerNames): SearchMessageRow {
    const { chatId, teamId, channelId } = row;
    return {
      ...row,
      chatName: chatId ? (names.chats.get(chatId) ?? null) : null,
      teamName: teamId ? (names.teams.get(teamId) ?? null) : null,
      channelName:
        teamId && channelId ? (names.channels.get(channelKey(teamId, channelId)) ?? null) : null,
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

            // The hit's own fields only fill gaps, so a row reads the same
            // whether or not the fetch landed. `webUrl` is never taken from the
            // message: chatmessage-get returns null for a chat message and would
            // blank the link the hit gave us.
            return {
              ...row,
              senderDisplayName:
                row.senderDisplayName ?? message.from?.displayName ?? senderAddress,
              // The hit's timestamp is the index time, not the creation time: a
              // message created 09:13:45.444 (its id is that epoch) came back
              // from search as 09:39:33. The fetched message is authoritative.
              createdDateTime: message.createdDateTime ?? row.createdDateTime,
              message,
            };
          } catch (error) {
            // One deleted or forbidden message must not fail the page. Logged at
            // warn because a tenant without consent for channel messages fails
            // every channel hit, and that must show without debug logging.
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
