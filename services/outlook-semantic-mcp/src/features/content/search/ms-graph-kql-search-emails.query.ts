import { isUpstreamCredentialRevokedError } from '@unique-ag/mcp-oauth';
import { createSmeared } from '@unique-ag/utils';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { groupBy, unique, uniqueBy } from 'remeda';
import { typeid } from 'typeid-js';
import * as z from 'zod';
import { UserProfile } from '~/db';
import { RemoveDelegatedAccessCommand } from '~/features/delegated-access/commands/remove-delegated-access.command';
import { TranslateGraphIdsToImmutableIdsQuery } from '~/features/graph-utils/translate-graph-ids-to-immutable-ids.query';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { convertDateTimeToTimezone } from '~/utils/convert-datetime-to-timezone';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { NonNullishProps } from '~/utils/non-nullish-props';
import { safeStringify } from '~/utils/safe-stringify';
import { sanitizeKqlQuery } from '~/utils/sanitize-kql-query';
import { sleep } from '~/utils/sleep';
import {
  BuildMsGraphKqlBatchRequestsQuery,
  GraphBatchRequest,
  QueryInput,
} from './build-ms-graph-kql-batch-requests.query';
import {
  BackendPage,
  MsGraphSearchCursorPayload,
  StoredSearchCursor,
} from './cursors/search-cursor.payload';
import { SEARCH_CONFIG } from './search.config';
import { SearchBackend, SearchEmailResult, SearchPageStatus } from './search-results.types';

const GRAPH_API_VERSION_PREFIX = '/v1.0';
const MESSAGE_SELECT_FIELDS =
  'subject,from,sentDateTime,receivedDateTime,parentFolderId,webLink,bodyPreview,isDraft';
const DEFAULT_RETRY_AFTER_MS = 500;
const DEFAULT_RETRY_AFTER_SECONDS_FOR_AGENT = 30;
const BATCH_SIZE = 20;

const batchResponseSchema = z.object({
  responses: z.array(
    z.object({
      id: z.string(),
      status: z.number(),
      headers: z.record(z.string(), z.string()).optional(),
      body: z.unknown(),
    }),
  ),
});

const messagePageSchema = z.object({
  value: z.array(
    z.object({
      id: z.string(),
      subject: z.string().optional().nullish(),
      from: z
        .object({ emailAddress: z.object({ address: z.string() }) })
        .optional()
        .nullish(),
      sentDateTime: z.string().optional().nullish(),
      receivedDateTime: z.string().optional().nullish(),
      parentFolderId: z.string().optional().nullish(),
      webLink: z.string().optional().nullish(),
      bodyPreview: z.string().optional().nullish(),
      isDraft: z.boolean().optional().nullish(),
    }),
  ),
  '@odata.nextLink': z.string().optional(),
});

interface Hit {
  restId: string;
  mailbox: string;
  isDelegated: boolean;
  subject: string;
  from: string;
  rawSentDateTime: string;
  rawReceivedDateTime: string;
  receivedDateTime: string | null;
  parentFolderId: string;
  webLink: string;
  bodyPreview: string;
  isDraft: boolean;
}

// One Graph request: the first page of a (query × mailbox × folder), or the page a cursor points at.
interface PageRequest {
  requestId: string;
  kqlQuery: string;
  mailbox: string;
  isDelegated: boolean;
  folderId?: string;
  folderName?: string;
  // Relative to the API version root.
  url: string;
  delivered: number;
  chainHead?: ChainHead;
  sourceCursorId?: string;
  // When the followed cursor was stored, i.e. how old its nextLink is.
  sourceCursorCreatedAt?: Date;
}

type ChainHead = NonNullable<MsGraphSearchCursorPayload['chainHead']>;

type RequestOutcome =
  | { type: 'ok'; request: PageRequest; hits: Hit[]; nextUrl: string | undefined }
  // The page was delivered, but Graph returned an @odata.nextLink that cannot be followed.
  | { type: 'unfollowable'; request: PageRequest; hits: Hit[] }
  // Graph served the chain's first page again for a nextLink it could no longer use.
  | { type: 'restarted'; request: PageRequest }
  | { type: 'retryable'; request: PageRequest; status: number | undefined; retryAfterMs?: number }
  | { type: 'lostAccess'; request: PageRequest }
  | { type: 'rejected'; request: PageRequest };

export interface MsGraphKqlSearchOutput {
  results: SearchEmailResult[];
  pages: BackendPage[];
  searchSummary: string | undefined;
}

const getRequestId = () => typeid('batch_request').toString();

const MINUTE_MS = 60 * 1000;

const buildFirstPageUrl = (request: GraphBatchRequest, top: number): string => {
  const base = request.folderId
    ? `/users/${request.mailbox}/mailFolders/${request.folderId}/messages`
    : `/users/${request.mailbox}/messages`;
  const search = encodeURIComponent(sanitizeKqlQuery(request.kqlQuery));
  return `${base}?$search=${search}&$select=${MESSAGE_SELECT_FIELDS}&$top=${top}`;
};

const getFirstPageSize = (limit: number, requestCount: number): number =>
  Math.min(
    limit,
    Math.max(
      SEARCH_CONFIG.minFirstPageSize,
      Math.floor(SEARCH_CONFIG.firstCallGraphResultBudget / requestCount),
    ),
  );

// $batch sub-requests take URLs relative to the API version root, @odata.nextLink is absolute.
export const toRelativeGraphUrl = (nextLink: string): string | undefined => {
  const url = URL.parse(nextLink);
  if (!url?.pathname.startsWith(`${GRAPH_API_VERSION_PREFIX}/`)) {
    return undefined;
  }
  return `${url.pathname.slice(GRAPH_API_VERSION_PREFIX.length)}${url.search}`;
};

const toChainHead = (hit: Hit | undefined): ChainHead | undefined =>
  hit?.rawSentDateTime ? { id: hit.restId, sentDateTime: hit.rawSentDateTime } : undefined;

// Graph pages by offset, newest sent first, so a genuine later page only holds emails sent no later
// than the head. Enough new mail arriving between two fetches also trips this, and expiring the
// chain is the right answer then too, because the page would repeat results.
const isRestartedChain = (head: ChainHead, hits: Hit[]): boolean => {
  const headSentAt = Date.parse(head.sentDateTime);
  return hits.some((hit) => hit.restId === head.id || Date.parse(hit.rawSentDateTime) > headSentAt);
};

@Injectable()
export class MsGraphKqlSearchEmailsQuery {
  private readonly logger = new Logger(MsGraphKqlSearchEmailsQuery.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getUserProfileQuery: GetUserProfileQuery,
    private readonly translateGraphIdsToImmutableIdsQuery: TranslateGraphIdsToImmutableIdsQuery,
    private readonly buildMsGraphKqlBatchRequestsQuery: BuildMsGraphKqlBatchRequestsQuery,
    private readonly removeDelegatedAccessCommand: RemoveDelegatedAccessCommand,
  ) {}

  @Span()
  public async run(
    userProfileId: UserProfileTypeID,
    queries: Array<QueryInput>,
    outputTimeZone?: string,
  ): Promise<MsGraphKqlSearchOutput> {
    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    const { requests, skippedFolders, queriedMailboxesWithoutFullAccess } =
      await this.buildMsGraphKqlBatchRequestsQuery.run(userProfileId, queries);

    if (!requests.length) {
      return {
        results: [],
        pages: [],
        searchSummary: this.buildSearchSummary({
          queriedMailboxesWithoutFullAccess,
          skippedFolders,
          throttledMailboxes: new Set(),
          lostAccessMailboxes: new Set(),
          additionalMessages: [`Your queries do not match any inbox which you can access`],
        }),
      };
    }

    const pageRequests = requests.map(
      (request): PageRequest => ({
        requestId: request.requestId,
        kqlQuery: request.kqlQuery,
        mailbox: request.mailbox,
        isDelegated: request.isDelegated,
        folderId: request.folderId,
        folderName: request.folderName,
        url: buildFirstPageUrl(request, getFirstPageSize(request.limit, requests.length)),
        delivered: 0,
      }),
    );

    return this.executePages(userProfile, pageRequests, outputTimeZone, {
      skippedFolders,
      queriedMailboxesWithoutFullAccess,
    });
  }

  @Span()
  public async fetchNextPages(
    userProfileId: UserProfileTypeID,
    cursors: StoredSearchCursor<MsGraphSearchCursorPayload>[],
    outputTimeZone?: string,
  ): Promise<MsGraphKqlSearchOutput> {
    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    const pageRequests = cursors.map(
      ({ id, payload, createdAt }): PageRequest => ({
        requestId: getRequestId(),
        kqlQuery: payload.kqlQuery,
        mailbox: payload.mailbox,
        isDelegated: payload.isDelegated,
        folderId: payload.folderId,
        folderName: payload.folderName,
        url: payload.url,
        delivered: payload.delivered,
        chainHead: payload.chainHead,
        sourceCursorId: id,
        sourceCursorCreatedAt: createdAt,
      }),
    );

    return this.executePages(userProfile, pageRequests, outputTimeZone, {
      skippedFolders: [],
      queriedMailboxesWithoutFullAccess: [],
    });
  }

  private async executePages(
    userProfile: NonNullishProps<UserProfile, 'email'>,
    pageRequests: PageRequest[],
    outputTimeZone: string | undefined,
    buildNotes: {
      skippedFolders: { mailbox: string; folder: string }[];
      queriedMailboxesWithoutFullAccess: string[];
    },
  ): Promise<MsGraphKqlSearchOutput> {
    const round1 = await this.executeBatchRound(pageRequests, userProfile, outputTimeZone);
    const round1LostMailboxes = new Set(
      round1
        .filter((outcome) => outcome.type === 'lostAccess')
        .map(({ request }) => request.mailbox),
    );
    const isRetryable = (outcome: RequestOutcome) =>
      outcome.type === 'retryable' && !round1LostMailboxes.has(outcome.request.mailbox);
    const toRetry = round1.filter(
      (outcome): outcome is Extract<RequestOutcome, { type: 'retryable' }> => isRetryable(outcome),
    );
    if (toRetry.length > 0) {
      const retryAfterMs = Math.max(
        DEFAULT_RETRY_AFTER_MS,
        ...toRetry.map((outcome) => outcome.retryAfterMs ?? 0),
      );
      await sleep(retryAfterMs);
    }
    const round2 = await this.executeBatchRound(
      toRetry.map(({ request }) => request),
      userProfile,
      outputTimeZone,
    );
    const outcomes = [...round1.filter((outcome) => !isRetryable(outcome)), ...round2];

    const lostAccessMailboxes = new Set(
      outcomes
        .filter((outcome) => outcome.type === 'lostAccess')
        .map(({ request }) => request.mailbox),
    );
    // Network failures carry no status and are not reported per mailbox.
    const throttledMailboxes = new Set(
      round2
        .filter((outcome) => outcome.type === 'retryable' && outcome.status !== undefined)
        .map(({ request }) => request.mailbox),
    );

    const hits = outcomes
      .flatMap((outcome) =>
        outcome.type === 'ok' || outcome.type === 'unfollowable' ? outcome.hits : [],
      )
      .filter((hit) => !lostAccessMailboxes.has(hit.mailbox));

    return {
      results: await this.buildResults(userProfile, hits),
      pages: outcomes.map((outcome) => this.toBackendPage(outcome, lostAccessMailboxes)),
      searchSummary: this.buildSearchSummary({
        ...buildNotes,
        throttledMailboxes,
        lostAccessMailboxes,
      }),
    };
  }

  private async buildResults(
    userProfile: NonNullishProps<UserProfile, 'email'>,
    hits: Hit[],
  ): Promise<SearchEmailResult[]> {
    // Graph sorts each page by sent date. Results from several requests are merged newest first.
    const uniqueHits = uniqueBy(hits, ({ restId }) => restId).sort((a, b) =>
      b.rawReceivedDateTime.localeCompare(a.rawReceivedDateTime),
    );

    const idsTranslationMaps = new Map<string, Map<string, string>>(
      await Promise.all(
        Object.entries(groupBy(uniqueHits, (hit) => hit.mailbox)).map(
          async ([mailbox, mailboxHits]) => {
            const translationMap = await this.translateGraphIdsToImmutableIdsQuery.run({
              userProfileId: userProfile.id,
              ids: mailboxHits.map(({ restId }) => restId),
              ownerEmail: mailbox === userProfile.email ? undefined : mailbox,
            });
            return [mailbox, translationMap] as const;
          },
        ),
      ),
    );

    return uniqueHits.map((hit): SearchEmailResult => {
      const translatedId = idsTranslationMaps.get(hit.mailbox)?.get(hit.restId);
      const idIsImmutable = translatedId !== undefined;
      const id = translatedId ?? hit.restId;

      return {
        msGraphMessageId: id,
        folderId: hit.parentFolderId,
        title: hit.subject,
        from: hit.from,
        sourceMailbox: hit.mailbox,
        outlookWebLink: hit.webLink,
        receivedDateTime: hit.receivedDateTime,
        text: hit.bodyPreview,
        uniqueContentUrl: undefined,
        backend: SearchBackend.MsGraph,
        openEmailParams: {
          id,
          idType: SearchBackend.MsGraph,
          mailbox: hit.isDelegated ? hit.mailbox : undefined,
          parentFolderId: hit.isDelegated ? hit.parentFolderId : undefined,
          idIsImmutable,
        },
        replyToParams: {
          inReplyToMessageId: id,
          idIsImmutable,
          isReplyable: !hit.isDraft,
        },
      };
    });
  }

  private toBackendPage(outcome: RequestOutcome, lostAccessMailboxes: Set<string>): BackendPage {
    const { request } = outcome;
    const page = {
      backend: SearchBackend.MsGraph,
      query: request.kqlQuery,
      mailbox: request.mailbox,
      folder: request.folderName,
    };
    const position = {
      backend: SearchBackend.MsGraph as const,
      kqlQuery: request.kqlQuery,
      mailbox: request.mailbox,
      isDelegated: request.isDelegated,
      folderId: request.folderId,
      folderName: request.folderName,
    };

    if (lostAccessMailboxes.has(request.mailbox)) {
      return { ...page, status: SearchPageStatus.AccessRevoked };
    }

    switch (outcome.type) {
      case 'ok': {
        const delivered = request.delivered + outcome.hits.length;
        if (delivered >= SEARCH_CONFIG.maxResultsPerChain) {
          return { ...page, status: SearchPageStatus.CeilingReached };
        }
        if (!outcome.nextUrl) {
          return { ...page, status: SearchPageStatus.Complete };
        }
        return {
          ...page,
          status: SearchPageStatus.HasMore,
          continuation: {
            ...position,
            url: outcome.nextUrl,
            delivered,
            chainHead: request.chainHead ?? toChainHead(outcome.hits[0]),
          },
        };
      }
      case 'unfollowable':
        return { ...page, status: SearchPageStatus.Failed };
      case 'restarted':
        return { ...page, status: SearchPageStatus.Expired };
      case 'retryable': {
        const isThrottled = outcome.status === 429;
        return {
          ...page,
          status: isThrottled ? SearchPageStatus.Throttled : SearchPageStatus.Failed,
          retryAfterSeconds: isThrottled
            ? outcome.retryAfterMs
              ? Math.ceil(outcome.retryAfterMs / 1000)
              : DEFAULT_RETRY_AFTER_SECONDS_FOR_AGENT
            : undefined,
          continuation: {
            ...position,
            url: request.url,
            delivered: request.delivered,
            chainHead: request.chainHead,
          },
          retryCursorId: request.sourceCursorId,
        };
      }
      case 'lostAccess':
        return { ...page, status: SearchPageStatus.AccessRevoked };
      case 'rejected':
        // A stored nextLink that Graph no longer accepts has expired. A rejected first page is a
        // query Graph cannot run, so there is nothing to retry.
        return {
          ...page,
          status: request.sourceCursorId ? SearchPageStatus.Expired : SearchPageStatus.Failed,
        };
    }
  }

  private async executeBatchRound(
    requests: PageRequest[],
    userProfile: NonNullishProps<UserProfile, 'email'>,
    outputTimeZone: string | undefined,
  ): Promise<RequestOutcome[]> {
    const client = this.graphClientFactory.createClientForUser(userProfile.id);
    const outcomes: RequestOutcome[] = [];
    const lostAccessMailboxes = new Set<string>();

    for (let start = 0; start < requests.length; start += BATCH_SIZE) {
      const chunk = requests.slice(start, start + BATCH_SIZE);
      const batch = chunk.filter((request) => !lostAccessMailboxes.has(request.mailbox));
      outcomes.push(
        ...chunk
          .filter((request) => lostAccessMailboxes.has(request.mailbox))
          .map((request): RequestOutcome => ({ type: 'lostAccess', request })),
      );
      if (!batch.length) {
        continue;
      }

      let batchResponse: z.infer<typeof batchResponseSchema>;
      try {
        const raw = await client.api('$batch').post({
          requests: batch.map((request) => ({
            id: request.requestId,
            method: 'GET',
            url: request.url,
          })),
        });
        batchResponse = batchResponseSchema.parse(raw);
      } catch (error) {
        // A revoked Microsoft grant would otherwise be retried and then reported as an empty
        // mailbox, which reads as a real answer. Let it reach the caller so they re-authenticate.
        if (isUpstreamCredentialRevokedError(error)) {
          throw error;
        }
        outcomes.push(
          ...batch.map(
            (request): RequestOutcome => ({ type: 'retryable', request, status: undefined }),
          ),
        );
        continue;
      }

      for (const request of batch) {
        const subResponse = batchResponse.responses.find((item) => item.id === request.requestId);
        if (!subResponse) {
          outcomes.push({ type: 'retryable', request, status: undefined });
          continue;
        }
        const outcome = await this.toRequestOutcome(
          request,
          subResponse,
          userProfile,
          outputTimeZone,
        );
        if (outcome.type === 'lostAccess') {
          lostAccessMailboxes.add(request.mailbox);
        }
        outcomes.push(outcome);
      }
    }

    return outcomes;
  }

  private async toRequestOutcome(
    request: PageRequest,
    subResponse: z.infer<typeof batchResponseSchema>['responses'][number],
    userProfile: NonNullishProps<UserProfile, 'email'>,
    outputTimeZone: string | undefined,
  ): Promise<RequestOutcome> {
    const { status } = subResponse;

    if (status === 429 || status >= 500) {
      const retryAfterHeader =
        subResponse.headers?.['Retry-After'] ?? subResponse.headers?.['retry-after'];
      const seconds = retryAfterHeader ? parseInt(retryAfterHeader, 10) : Number.NaN;
      return {
        type: 'retryable',
        request,
        status,
        retryAfterMs: Number.isNaN(seconds) ? undefined : seconds * 1000,
      };
    }

    if (request.isDelegated && (status === 403 || status === 404)) {
      if (this.isOldNextLink(request)) {
        return { type: 'rejected', request };
      }
      await this.removeDelegatedAccessCommand.run({
        delegateUserId: userProfile.id,
        ownerEmail: request.mailbox,
        where: { fullAccess: true },
      });
      return { type: 'lostAccess', request };
    }

    const details = {
      mailbox: createSmeared(request.mailbox),
      kqlQuery: createSmeared(request.kqlQuery),
      body: createSmeared(safeStringify(subResponse.body)),
    };

    if (status < 200 || status >= 300) {
      this.logger.error({ ...details, msg: 'MS Graph batch sub-request failed', status });
      return { type: 'rejected', request };
    }

    const parsed = messagePageSchema.safeParse(subResponse.body);
    if (!parsed.success) {
      this.logger.error({
        ...details,
        msg: 'MS Graph message response failed schema validation',
        error: parsed.error,
      });
      return { type: 'rejected', request };
    }

    // The $search parameter causes Graph to return webLinks in the classic OWA format
    // (outlook.office365.com/owa/?ItemID={restId}&…) rather than the new
    // outlook.cloud.microsoft format that regular GET/POST endpoints return on migrated
    // tenants. The classic format embeds a RestId, which OWA accepts — so these webLinks
    // work as-is without any ID translation, even for delegated mailboxes.
    const hits = parsed.data.value.map(
      (msg): Hit => ({
        restId: msg.id,
        mailbox: request.mailbox,
        isDelegated: request.isDelegated,
        subject: msg.subject ?? '',
        from: msg.from?.emailAddress.address ?? '',
        rawSentDateTime: msg.sentDateTime ?? '',
        rawReceivedDateTime: msg.receivedDateTime ?? '',
        receivedDateTime: convertDateTimeToTimezone(msg.receivedDateTime, outputTimeZone) ?? null,
        parentFolderId: msg.parentFolderId ?? '',
        webLink: msg.webLink ?? '',
        bodyPreview: msg.bodyPreview ?? '',
        isDraft: msg.isDraft === true,
      }),
    );

    if (request.chainHead && isRestartedChain(request.chainHead, hits)) {
      this.logger.warn({
        mailbox: details.mailbox,
        kqlQuery: details.kqlQuery,
        msg: 'MS Graph restarted a search chain from its first page',
      });
      return { type: 'restarted', request };
    }

    const nextLink = parsed.data['@odata.nextLink'];
    if (nextLink === undefined) {
      return { type: 'ok', request, hits, nextUrl: undefined };
    }
    const nextUrl = toRelativeGraphUrl(nextLink);
    if (!nextUrl) {
      this.logger.error({
        mailbox: details.mailbox,
        kqlQuery: details.kqlQuery,
        nextLink: createSmeared(nextLink),
        msg: 'MS Graph returned an @odata.nextLink outside the v1.0 API',
      });
      return { type: 'unfollowable', request, hits };
    }
    return { type: 'ok', request, hits, nextUrl };
  }

  private isOldNextLink({ sourceCursorCreatedAt }: PageRequest): boolean {
    return (
      sourceCursorCreatedAt !== undefined &&
      Date.now() - sourceCursorCreatedAt.getTime() >
        SEARCH_CONFIG.maxNextLinkAgeForAccessRevocationMinutes * MINUTE_MS
    );
  }

  private buildSearchSummary({
    throttledMailboxes,
    lostAccessMailboxes,
    queriedMailboxesWithoutFullAccess,
    skippedFolders,
    additionalMessages,
  }: {
    throttledMailboxes: Set<string>;
    lostAccessMailboxes: Set<string>;
    queriedMailboxesWithoutFullAccess: string[];
    skippedFolders: { mailbox: string; folder: string }[];
    additionalMessages?: string[];
  }): string | undefined {
    const byMailbox = groupBy(skippedFolders, ({ mailbox }) => mailbox);
    const summaryParts = [
      ...(throttledMailboxes.size > 0
        ? [
            `Microsoft throttled or could not complete the search in the following mailboxes: ${Array.from(throttledMailboxes).sort().join(', ')}. Their results are incomplete; retry those pages later.`,
          ]
        : []),
      ...(lostAccessMailboxes.size > 0
        ? [
            `Access to the following mailboxes was revoked: ${Array.from(lostAccessMailboxes).sort().join(', ')}.`,
          ]
        : []),
      ...(queriedMailboxesWithoutFullAccess.length > 0
        ? [
            `Could not search in the following mailboxes: ${unique(queriedMailboxesWithoutFullAccess).sort().join(', ')}. Microsoft does not offer an api to search in shared folders from this mailbox.`,
          ]
        : []),
      ...Object.entries(byMailbox).map(
        ([mailbox, entries]) =>
          `The following folders '${unique(entries.map(({ folder }) => folder))
            .sort()
            .join(', ')}' in mailbox ${mailbox} were excluded because they were not recognized.`,
      ),
      ...(additionalMessages ?? []),
    ];

    return summaryParts.length > 0 ? summaryParts.join('\n') : undefined;
  }
}
