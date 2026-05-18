import { createSmeared } from '@unique-ag/utils';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { chunk, filter, groupBy, pipe } from 'remeda';
import { typeid } from 'typeid-js';
import * as z from 'zod';
import { UserProfile } from '~/db';
import {
  SearchBackend,
  SearchEmailResult,
} from '~/features/content/search/semantic-search-emails.query';
import { MarkAccountsNoFullAccessCommand } from '~/features/delegated-access/commands/mark-accounts-no-full-access.command';
import { GetMailboxesWithFullDelegatedAccessQuery } from '~/features/delegated-access/queries/get-mailboxes-with-full-delegated-access.query';
import { TranslateGraphIdsToImmutableIdsQuery } from '~/features/graph-utils/translate-graph-ids-to-immutable-ids.query';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { NonNullishProps } from '~/utils/non-nullish-props';
import { sanitizeKqlQuery } from '~/utils/sanitize-kql-query';
import { MsGraphSearchConfig } from './search.config';

const batchResponseSchema = z.object({
  responses: z.array(
    z.object({
      id: z.string(),
      status: z.number(),
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

interface GraphBatchRequest {
  requestId: string;
  mailbox: string;
  isDelegated: boolean;
  kqlQuery: string;
  limit: number;
}

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

interface QueryInput {
  kqlQuery: string;
  limit?: number;
  mailbox?: string | null | undefined;
}

@Injectable()
export class MsGraphKqlSearchEmailsQuery {
  private readonly logger = new Logger(MsGraphKqlSearchEmailsQuery.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getUserProfileQuery: GetUserProfileQuery,
    private readonly translateGraphIdsToImmutableIdsQuery: TranslateGraphIdsToImmutableIdsQuery,
    private readonly getMailboxesWithFullDelegatedAccessQuery: GetMailboxesWithFullDelegatedAccessQuery,
    private readonly markAccountsNoFullAccessCommand: MarkAccountsNoFullAccessCommand,
  ) {}

  @Span()
  public async run(
    userProfileId: UserProfileTypeID,
    queries: Array<QueryInput>,
    searchConfig: MsGraphSearchConfig,
  ): Promise<{ results: SearchEmailResult[]; searchSummary: string | undefined }> {
    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    const msGraphBatchRequest: GraphBatchRequest[] = await this.translateQueriesToBatchRequests({
      userProfile,
      queries,
    });

    if (!msGraphBatchRequest.length) {
      return {
        results: [],
        searchSummary: [
          `In order to get results we need at least 1 valid query to execute. `,
          `Your queries do not match any inbox which you can access`,
        ].join(''),
      };
    }

    const fetchResult = await this.fetchFromMicrosoft({
      userProfile,
      batchRequests: msGraphBatchRequest,
      searchConfig,
    });
    if (!fetchResult.success) {
      return { results: [], searchSummary: fetchResult.searchSummary };
    }

    const hitsByMailbox = groupBy(fetchResult.hits, (item) => item.mailbox);
    const idsTranslationMaps = new Map<string, Map<string, string>>(
      await Promise.all(
        Object.entries(hitsByMailbox).map(async ([mailbox, hits]) => {
          const translationMap = await this.translateGraphIdsToImmutableIdsQuery.run({
            userProfileId: userProfile.id,
            ids: hits.map(({ restId }) => restId),
            ownerEmail: mailbox === userProfile.email ? undefined : mailbox,
          });
          return [mailbox, translationMap] as const;
        }),
      ),
    );

    const results: SearchEmailResult[] = [];

    for (const hit of fetchResult.hits) {
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

    return { results, searchSummary: undefined };
  }

  private async translateQueriesToBatchRequests({
    userProfile,
    queries,
  }: {
    queries: Array<QueryInput>;
    userProfile: NonNullishProps<UserProfile, 'email'>;
  }) {
    const delegatedAccesses = await this.getMailboxesWithFullDelegatedAccessQuery.run({
      delegateUserId: userProfile.id,
    });
    const getRequestId = () => typeid(`batch_request`).toString();

    return queries.flatMap((query): GraphBatchRequest[] => {
      const limit = query.limit ?? 100;
      const { mailbox } = query;

      if (mailbox) {
        if (mailbox === userProfile.email) {
          return [
            {
              requestId: getRequestId(),
              mailbox: userProfile.email,
              isDelegated: false,
              kqlQuery: query.kqlQuery,
              limit,
            },
          ];
        }

        const foundMailbox = delegatedAccesses.find((item) => mailbox === item);
        if (!foundMailbox) {
          return [];
        }

        return [
          {
            requestId: getRequestId(),
            mailbox: foundMailbox,
            isDelegated: true,
            kqlQuery: query.kqlQuery,
            limit,
          },
        ];
      }

      // For safety to not expload the number of request we cap the delegated access search to 25. 25 Is not an arbitrary number
      // Microsoft documents that a exchange user can have delegated access to at most 25 other inboxes.
      const delegatesToFilter = delegatedAccesses.slice(0, 25);
      return [
        {
          requestId: getRequestId(),
          mailbox: userProfile.email,
          isDelegated: false,
          kqlQuery: query.kqlQuery,
          limit,
        },
        ...delegatesToFilter.map((ownerEmail) => ({
          requestId: getRequestId(),
          mailbox: ownerEmail,
          isDelegated: true,
          kqlQuery: query.kqlQuery,
          limit,
        })),
      ];
    });
  }

  private async fetchFromMicrosoft({
    userProfile,
    batchRequests,
    searchConfig,
  }: {
    userProfile: NonNullishProps<UserProfile, 'email'>;
    batchRequests: GraphBatchRequest[];
    searchConfig: MsGraphSearchConfig;
  }): Promise<
    | {
        success: false;
        searchSummary: string;
      }
    | {
        success: true;
        hits: Hit[];
      }
  > {
    const client = this.graphClientFactory.createClientForUser(userProfile.id);
    const mailboxesWhichLostAccess = new Set<string>();
    const allHits: Hit[] = [];

    for (const batch of chunk(batchRequests, 20)) {
      let batchResponse: z.infer<typeof batchResponseSchema>;
      try {
        const raw = await client.api('$batch').post({
          requests: batch.map((request) => {
            const searchParams = new URLSearchParams();
            searchParams.set(`$search`, sanitizeKqlQuery(request.kqlQuery));

            return {
              id: request.requestId,
              method: 'GET',
              url: `/users/${request.mailbox}/messages?${searchParams.toString()}`,
              headers: { Prefer: 'outlook.body-content-type="text"' },
            };
          }),
        });
        batchResponse = batchResponseSchema.parse(raw);
      } catch {
        return {
          success: false,
          searchSummary: 'KQL search is currently unavailable; results were not returned.',
        };
      }

      for (const subResponse of batchResponse.responses) {
        const originalRequest = batch.find((item) => subResponse.id === item.requestId);
        if (!originalRequest) {
          continue;
        }

        const status = subResponse.status;

        if (originalRequest.isDelegated && (status === 403 || status === 404)) {
          mailboxesWhichLostAccess.add(originalRequest.mailbox);
          this.markAccountsNoFullAccessCommand
            .run({ delegateUserId: userProfile.id, ownerEmail: originalRequest.mailbox })
            .catch(() => undefined);
          continue;
        }

        const details = {
          mailbox: createSmeared(originalRequest.mailbox),
          kqlQuery: createSmeared(originalRequest.kqlQuery),
          body: createSmeared(subResponse.body?.toString() ?? ``),
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
          allHits.push({
            restId: msg.id,
            mailbox: originalRequest.mailbox,
            isDelegated: originalRequest.isDelegated,
            subject: msg.subject ?? '',
            from: msg.from?.emailAddress.address ?? '',
            receivedDateTime: msg.receivedDateTime ?? null,
            parentFolderId: msg.parentFolderId ?? '',
            webLink: msg.webLink ?? '',
            text: msg.uniqueBody?.content ?? msg.body?.content ?? msg.bodyPreview ?? '',
          });
        }
      }
    }

    const results = pipe(
      allHits,
      filter((item) => !mailboxesWhichLostAccess.has(item.mailbox)),
      groupBy((item) => item.mailbox),
    );

    return { success: true, hits: this.mergeResults(results, searchConfig) };
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
        const item = itemsList?.[index];
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
