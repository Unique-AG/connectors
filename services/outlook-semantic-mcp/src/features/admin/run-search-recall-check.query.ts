import { UniqueApiClient } from '@unique-ag/unique-api';
import { Inject, Injectable } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { pick } from 'remeda';
import * as z from 'zod';
import { DRIZZLE, DrizzleDatabase, directories } from '~/db';
import { SearchEmailsInputSchema } from '~/features/content/search/semantic-search-conditions.dto';
import { SemanticSearchEmailsQuery } from '~/features/content/search/semantic-search-emails.query';
import { traceAttrs, traceError } from '~/features/tracing.utils';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { Nullish } from '~/utils/nullish';
import { FAILED_INGESTION_STATUSES } from '../sync/full-sync/get-scope-ingestion-stats.query';
import { FetchMessagesFromGraphQuery } from './fetch-messages-from-graph.query';

export interface SearchRecallCheckCase {
  id: string;
  graphFilter?: string;
  graphSearch?: string;
  search: z.infer<typeof SearchEmailsInputSchema>;
}

interface SearchRecallCommonResponse {
  id: string;
  accuracy: string;
  stats: {
    graphEmailsCount: number;
    searchEmailsCount: number;
    missedEmailsCount: number;
    foundEmailsCount: number;
  };
  inputParams: {
    graphFilter?: string;
    graphSearch?: string;
    search: z.infer<typeof SearchEmailsInputSchema>;
  };
}

interface SearchRecallCheckSuccessResult extends SearchRecallCommonResponse {
  checkStatus: 'success';
}

interface SearchRecallCheckFailureResult extends SearchRecallCommonResponse {
  checkStatus: 'failure';
  missedMessages: {
    missedMessagesInUniqueCount: number;
    missedMessagesInUniqueWithFailedIngestionCount: number;
    items: {
      messageId: string;
      fileKey: string;
      existsInUnique: boolean;
      ingestionState: string | undefined;
      directoryId: Nullish<string>;
      directoryName: Nullish<string>;
    }[];
  };
}

export type SearchRecallCheckCaseResult =
  | SearchRecallCheckSuccessResult
  | SearchRecallCheckFailureResult;

@Injectable()
export class RunSearchRecallCheckQuery {
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly fetchMessagesFromGraphQuery: FetchMessagesFromGraphQuery,
    private readonly searchEmailsQuery: SemanticSearchEmailsQuery,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
  ) {}

  @Span()
  public async run(
    userProfileId: string,
    cases: SearchRecallCheckCase[],
  ): Promise<SearchRecallCheckCaseResult[]> {
    try {
      return await this.runCheck(userProfileId, cases);
    } catch (error) {
      traceError(error);
      throw error;
    }
  }

  private async runCheck(
    userProfileId: string,
    cases: SearchRecallCheckCase[],
  ): Promise<SearchRecallCheckCaseResult[]> {
    traceAttrs({ userProfileId });
    const failedIngestionStates = new Set<string | undefined>(FAILED_INGESTION_STATUSES);

    const allDirectories = await this.db.query.directories.findMany({
      where: eq(directories.userProfileId, userProfileId),
    });
    const directoryByFolderId = new Map(allDirectories.map((d) => [d.providerDirectoryId, d]));

    return Promise.all(
      cases.map(async (checkCase): Promise<SearchRecallCheckCaseResult> => {
        const { notSkipped } = await this.fetchMessagesFromGraphQuery.run({
          userProfileId,
          filter: checkCase.graphFilter,
          search: checkCase.graphSearch,
        });

        const expectedMessageIds = notSkipped.map((e) => e.messageId);
        const { results } = await this.searchEmailsQuery.run(userProfileId, checkCase.search);
        const returnedEmailIds = new Set(results.map((r) => r.emailId));

        const missedMessagesBase = notSkipped
          .filter((msg) => !returnedEmailIds.has(msg.messageId))
          .map((msg) => ({
            messageId: msg.messageId,
            directoryId: msg.parentFolderId,
            fileKey: msg.fileKey,
          }));

        const existingFileKeys = new Map<string, string>();
        if (missedMessagesBase.length) {
          const files = await this.uniqueApi.files.getByKeys(
            missedMessagesBase.map((m) => m.fileKey),
          );
          files.forEach((file) => {
            existingFileKeys.set(file.key, file.ingestionState);
          });
        }

        const missedMessages = missedMessagesBase.map((item) => {
          return {
            ...item,
            existsInUnique: existingFileKeys.has(item.fileKey),
            ingestionState: existingFileKeys.get(item.fileKey),
            directoryName: directoryByFolderId.get(item.directoryId ?? `__NOPE__`)?.displayName,
          };
        });

        const foundEmailsCount = expectedMessageIds.length - missedMessages.length;
        const accuracy =
          expectedMessageIds.length === 0
            ? '100.00'
            : ((foundEmailsCount / expectedMessageIds.length) * 100).toFixed(2);

        const result: SearchRecallCommonResponse = {
          id: checkCase.id,
          accuracy,
          inputParams: pick(checkCase, ['graphFilter', 'graphSearch', 'search']),
          stats: {
            graphEmailsCount: expectedMessageIds.length,
            searchEmailsCount: returnedEmailIds.size,
            missedEmailsCount: missedMessages.length,
            foundEmailsCount: foundEmailsCount,
          },
        };

        if (missedMessages.length === 0) {
          return { checkStatus: 'success', ...result };
        }

        return {
          checkStatus: 'failure',
          ...result,
          missedMessages: {
            missedMessagesInUniqueCount: missedMessages.filter((item) => item.existsInUnique)
              .length,
            missedMessagesInUniqueWithFailedIngestionCount: missedMessages.filter(
              (item) => item.existsInUnique && failedIngestionStates.has(item.ingestionState),
            ).length,
            items: missedMessages,
          },
        };
      }),
    );
  }
}
