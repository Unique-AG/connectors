import { UniqueApiClient } from '@unique-ag/unique-api';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { pick } from 'remeda';
import * as z from 'zod';
import { SearchEmailsInputSchema } from '~/features/content/search/search-conditions.dto';
import { SearchEmailsQuery } from '~/features/content/search/search-emails.query';
import { getUniqueKeyForMessage } from '~/features/process-email/utils/get-unique-key-for-message';
import { traceAttrs, traceError } from '~/features/tracing.utils';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { FAILED_INGESTION_STATUSES } from '../sync/full-sync/get-scope-ingestion-stats.query';
import { FetchMessagesFromGraphQuery } from './fetch-messages-from-graph.query';

export interface SearchRecallCheckCase {
  graphFilter?: string;
  graphSearch?: string;
  search: z.infer<typeof SearchEmailsInputSchema>;
}

interface SearchRecallCommonResponse {
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
    }[];
  };
}

export type SearchRecallCheckCaseResult =
  | SearchRecallCheckSuccessResult
  | SearchRecallCheckFailureResult;

@Injectable()
export class RunSearchRecallCheckQuery {
  public constructor(
    private readonly fetchMessagesFromGraphQuery: FetchMessagesFromGraphQuery,
    private readonly searchEmailsQuery: SearchEmailsQuery,
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

    return Promise.all(
      cases.map(async (checkCase): Promise<SearchRecallCheckCaseResult> => {
        const { notSkipped, userEmail } = await this.fetchMessagesFromGraphQuery.run({
          userProfileId,
          filter: checkCase.graphFilter,
          search: checkCase.graphSearch,
        });

        const expectedMessageIds = notSkipped.map((e) => e.messageId);
        const { results } = await this.searchEmailsQuery.run(userProfileId, checkCase.search);
        const returnedEmailIds = new Set(results.map((r) => r.emailId));

        const missedMessagesBase = expectedMessageIds
          .filter((messageId) => !returnedEmailIds.has(messageId))
          .map((messageId) => ({
            messageId,
            fileKey: getUniqueKeyForMessage({ userEmail, messageId }),
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

        const missedMessages = missedMessagesBase.map((item) => ({
          ...item,
          existsInUnique: existingFileKeys.has(item.fileKey),
          ingestionState: existingFileKeys.get(item.fileKey),
        }));

        const foundEmails = expectedMessageIds.length - missedMessages.length;
        const accuracy =
          expectedMessageIds.length === 0
            ? '100.00'
            : ((foundEmails / expectedMessageIds.length) * 100).toFixed(2);

        const result: SearchRecallCommonResponse = {
          accuracy,
          inputParams: pick(checkCase, ['graphFilter', 'graphSearch', 'search']),
          stats: {
            graphEmailsCount: expectedMessageIds.length,
            searchEmailsCount: returnedEmailIds.size,
            missedEmailsCount: missedMessages.length,
            foundEmailsCount: foundEmails,
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
