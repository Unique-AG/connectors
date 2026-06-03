import { createSmeared } from '@unique-ag/utils';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { groupBy } from 'remeda';
import * as z from 'zod';
import { UserProfile } from '~/db';
import {
  SearchBackend,
  SearchEmailResult,
} from '~/features/content/search/semantic-search-emails.query';
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
import { MsGraphSearchConfig } from './search.config';

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

const messageSchema = z.object({
  value: z.array(
    z.object({
      id: z.string(),
      subject: z.string().optional().nullish(),
      from: z
        .object({ emailAddress: z.object({ address: z.string() }) })
        .optional()
        .nullish(),
      receivedDateTime: z.string().optional().nullish(),
      parentFolderId: z.string().optional().nullish(),
      webLink: z.string().optional().nullish(),
      uniqueBody: z.object({ content: z.string() }).optional().nullish(),
      body: z.object({ content: z.string() }).optional().nullish(),
      bodyPreview: z.string().optional().nullish(),
    }),
  ),
});

interface Hit {
  restId: string;
  mailbox: string;
  isDelegated: boolean;
  subject: string;
  from: string;
  receivedDateTime: string | null;
  parentFolderId: string;
  webLink: string;
  text: string;
}

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
    searchConfig: MsGraphSearchConfig,
    outputTimeZone?: string,
  ): Promise<{ results: SearchEmailResult[]; searchSummary: string | undefined }> {
    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    const {
      requests: allRequests,
      skippedFolders,
      queriedMailboxesWithoutFullAccess,
    } = await this.buildMsGraphKqlBatchRequestsQuery.run(userProfileId, queries);

    if (!allRequests.length) {
      return {
        results: [],
        searchSummary: [
          `In order to get results we need at least 1 valid query to execute. `,
          `Your queries do not match any inbox which you can access`,
        ].join(''),
      };
    }

    const round1 = await this.executeBatchRound(allRequests, userProfile, outputTimeZone);
    if (round1.retryRequests.length > 0) {
      await sleep(round1.retryAfterMs);
    }
    const round2 = await this.executeBatchRound(round1.retryRequests, userProfile, outputTimeZone);
    const hits = [...round1.hits, ...round2.hits];

    const throttledMailboxes = round2.throttledMailboxes;

    const lostAccessMailboxes = new Set([
      ...round1.lostAccessMailboxes,
      ...round2.lostAccessMailboxes,
    ]);

    const filteredHits = hits.filter((item) => !lostAccessMailboxes.has(item.mailbox));

    const hitsByMailbox = groupBy(filteredHits, (item) => item.mailbox);

    const idsTranslationMaps = new Map<string, Map<string, string>>(
      await Promise.all(
        Object.entries(hitsByMailbox).map(async ([mailbox, mailboxHits]) => {
          const translationMap = await this.translateGraphIdsToImmutableIdsQuery.run({
            userProfileId: userProfile.id,
            ids: mailboxHits.map(({ restId }) => restId),
            ownerEmail: mailbox === userProfile.email ? undefined : mailbox,
          });
          return [mailbox, translationMap] as const;
        }),
      ),
    );

    const results: SearchEmailResult[] = [];

    for (const hit of this.mergeResults(hitsByMailbox, searchConfig)) {
      const translationMap = idsTranslationMaps.get(hit.mailbox);
      const translatedId = translationMap?.get(hit.restId);
      const idIsImmutable = translatedId !== undefined;
      const id = translatedId ?? hit.restId;

      results.push({
        msGraphMessageId: id,
        folderId: hit.parentFolderId,
        title: hit.subject,
        from: hit.from,
        sourceMailbox: hit.mailbox,
        outlookWebLink: hit.isDelegated ? '' : hit.webLink,
        receivedDateTime: hit.receivedDateTime,
        text: hit.text,
        uniqueContentUrl: undefined,
        backend: SearchBackend.MsGraph,
        openEmailParams: {
          id,
          idType: SearchBackend.MsGraph,
          mailbox: hit.isDelegated ? hit.mailbox : undefined,
          parentFolderId: hit.isDelegated ? hit.parentFolderId : undefined,
          idIsImmutable,
        },
      });

      if (results.length >= searchConfig.maxEmailsLimit) {
        break;
      }
    }

    const summaryParts: string[] = [];

    if (throttledMailboxes.size > 0) {
      summaryParts.push('Search was throttled for some mailboxes — results may be incomplete.');
    }
    for (const mailbox of lostAccessMailboxes) {
      summaryParts.push(`Could not access mailbox ${mailbox} — it was excluded from results.`);
    }
    for (const mailbox of queriedMailboxesWithoutFullAccess) {
      summaryParts.push(
        `Could not search in mailbox ${mailbox} — Microsoft does not offer an api to search in shared folders from this mailbox.`,
      );
    }
    for (const { mailbox, folder } of skippedFolders) {
      summaryParts.push(
        `Folder '${folder}' in mailbox ${mailbox} was not recognized and was excluded.`,
      );
    }

    const searchSummary = summaryParts.length > 0 ? summaryParts.join('\n') : undefined;

    return { results, searchSummary };
  }

  private async executeBatchRound(
    requests: GraphBatchRequest[],
    userProfile: NonNullishProps<UserProfile, 'email'>,
    outputTimeZone: string | undefined,
  ): Promise<{
    hits: Hit[];
    retryRequests: GraphBatchRequest[];
    lostAccessMailboxes: Set<string>;
    throttledMailboxes: Set<string>;
    retryAfterMs: number;
  }> {
    const client = this.graphClientFactory.createClientForUser(userProfile.id);
    let queue = [...requests];
    const hits: Hit[] = [];
    const retryRequests: GraphBatchRequest[] = [];
    const lostAccessMailboxes = new Set<string>();
    const throttledMailboxes = new Set<string>();
    let retryAfterMs = -1;

    while (queue.length > 0) {
      const batch = queue.splice(0, 20);

      const batchApiInput = batch.map((request) => {
        const search = sanitizeKqlQuery(request.kqlQuery);
        const base = request.folderId
          ? `/users/${request.mailbox}/mailFolders/${request.folderId}/messages`
          : `/users/${request.mailbox}/messages`;
        return {
          id: request.requestId,
          method: 'GET',
          url: `${base}?$search=${encodeURIComponent(search)}&$select=subject,from,receivedDateTime,parentFolderId,webLink,uniqueBody,body,bodyPreview&$top=${request.limit}`,
          headers: { Prefer: 'outlook.body-content-type="text"' },
        };
      });

      let batchResponse: z.infer<typeof batchResponseSchema>;
      try {
        const raw = await client.api('$batch').post({ requests: batchApiInput });
        batchResponse = batchResponseSchema.parse(raw);
      } catch {
        retryRequests.push(...batch);
        continue;
      }

      for (const subResponse of batchResponse.responses) {
        const originalRequest = batch.find((item) => subResponse.id === item.requestId);
        if (!originalRequest) {
          continue;
        }

        const status = subResponse.status;

        if (status === 429 || status >= 500) {
          retryRequests.push(originalRequest);
          throttledMailboxes.add(originalRequest.mailbox);
          const retryAfterHeader =
            subResponse.headers?.['Retry-After'] ?? subResponse.headers?.['retry-after'];
          if (retryAfterHeader) {
            const seconds = parseInt(retryAfterHeader, 10);
            if (!Number.isNaN(seconds)) {
              retryAfterMs = Math.max(retryAfterMs, seconds * 1000);
            }
          }
          continue;
        }

        if (originalRequest.isDelegated && (status === 403 || status === 404)) {
          // Remove delegated access.
          await this.removeDelegatedAccessCommand.run({
            delegateUserId: userProfile.id,
            ownerEmail: originalRequest.mailbox,
            where: { fullAccess: true },
          });

          lostAccessMailboxes.add(originalRequest.mailbox);
          queue = queue.filter((item) => item.mailbox !== originalRequest.mailbox);
          continue;
        }

        const details = {
          mailbox: createSmeared(originalRequest.mailbox),
          kqlQuery: createSmeared(originalRequest.kqlQuery),
          body: createSmeared(safeStringify(subResponse.body)),
        };

        if (status < 200 || status >= 300) {
          this.logger.error({
            ...details,
            msg: 'MS Graph batch sub-request failed',
            status,
          });
          continue;
        }

        const parsed = messageSchema.safeParse(subResponse.body);
        if (!parsed.success) {
          this.logger.error({
            ...details,
            msg: 'MS Graph message response failed schema validation',
            error: parsed.error,
          });
          continue;
        }

        for (const msg of parsed.data.value) {
          hits.push({
            restId: msg.id,
            mailbox: originalRequest.mailbox,
            isDelegated: originalRequest.isDelegated,
            subject: msg.subject ?? '',
            from: msg.from?.emailAddress.address ?? '',
            receivedDateTime:
              convertDateTimeToTimezone(msg.receivedDateTime, outputTimeZone) ?? null,
            parentFolderId: msg.parentFolderId ?? '',
            webLink: msg.webLink ?? '',
            text: msg.uniqueBody?.content || msg.body?.content || msg.bodyPreview || '',
          });
        }
      }
    }

    return {
      hits,
      retryRequests,
      lostAccessMailboxes,
      throttledMailboxes,
      retryAfterMs: retryAfterMs <= 0 ? 500 : retryAfterMs,
    };
  }

  private mergeResults(
    hitsByMailbox: Record<string, Hit[]>,
    searchConfig: MsGraphSearchConfig,
  ): Hit[] {
    const allResults: Hit[] = [];
    const indicesMap = new Map(Object.keys(hitsByMailbox).map((mailbox) => [mailbox, 0]));
    let hasMoreItems = true;

    while (hasMoreItems) {
      hasMoreItems = false;

      for (const [mailbox, index] of Array.from(indicesMap)) {
        const itemsList = hitsByMailbox[mailbox];
        if (!itemsList) {
          indicesMap.delete(mailbox);
          continue;
        }
        const item = itemsList[index];
        if (!item) {
          indicesMap.delete(mailbox);
          continue;
        }

        if (!allResults.some((result) => result.restId === item.restId)) {
          allResults.push(item);
          if (allResults.length >= searchConfig.maxEmailsLimit) {
            return allResults;
          }
        }

        if (index + 1 < itemsList.length) {
          hasMoreItems = true;
          indicesMap.set(mailbox, index + 1);
        } else {
          indicesMap.delete(mailbox);
        }
      }
    }
    return allResults;
  }
}
