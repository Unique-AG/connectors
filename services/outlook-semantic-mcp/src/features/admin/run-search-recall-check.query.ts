import assert from 'node:assert';
import { Inject, Injectable } from '@nestjs/common';
import { UniqueApiClient } from '@unique-ag/unique-api';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { DRIZZLE, DrizzleDatabase, userProfiles } from '~/db';
import { SearchEmailsInputSchema } from '~/features/content/search/search-conditions.dto';
import { SearchEmailsQuery } from '~/features/content/search/search-emails.query';
import { getUniqueKeyForMessage } from '~/features/process-email/utils/get-unique-key-for-message';
import { traceAttrs, traceError } from '~/features/tracing.utils';
import { InjectUniqueApi } from '~/unique/unique-api.module';

export interface SearchRecallCheckCase {
  id: string;
  expectedMessageIds: string[];
  search: z.infer<typeof SearchEmailsInputSchema>;
}

export interface SearchRecallCheckCaseResult {
  id: string;
  searchParams: unknown;
  checkStatus: 'success' | 'failure';
  accuracy: string;
  missedMessages: {
    messageId: string;
    fileKey: string;
    existsInUnique: boolean;
    ingestionState: string | undefined;
  }[];
}

@Injectable()
export class RunSearchRecallCheckQuery {
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
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

    const userProfile = await this.db.query.userProfiles.findFirst({
      where: eq(userProfiles.id, userProfileId),
    });
    assert.ok(userProfile, `User profile not found: ${userProfileId}`);
    const userEmail = userProfile.email;
    assert.ok(userEmail, `User profile has no email: ${userProfileId}`);

    return Promise.all(
      cases.map(async (checkCase) => {
        const { results } = await this.searchEmailsQuery.run(userProfileId, checkCase.search);
        const returnedEmailIds = new Set(results.map((r) => r.emailId));

        const missedMessagesBase = checkCase.expectedMessageIds
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

        const foundEmails = checkCase.expectedMessageIds.length - missedMessages.length;
        const accuracy = ((foundEmails / checkCase.expectedMessageIds.length) * 100).toFixed(2);

        return {
          id: checkCase.id,
          searchParams: checkCase.search,
          checkStatus: missedMessages.length === 0 ? ('success' as const) : ('failure' as const),
          accuracy: `Found ${foundEmails} out of ${checkCase.expectedMessageIds.length}, ${missedMessages.length} missing. Accuracy ${accuracy}%`,
          missedMessages,
        };
      }),
    );
  }
}
