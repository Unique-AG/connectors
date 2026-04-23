import assert from 'node:assert';
import { UniqueApiClient } from '@unique-ag/unique-api';
import { createSmeared } from '@unique-ag/utils';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { DRIZZLE, DrizzleDatabase, userProfiles } from '~/db';
import { traceAttrs, traceError } from '~/features/tracing.utils';
import { getRootScopeExternalIdForUser } from '~/unique/get-root-scope-path';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { FetchMessagesFromGraphQuery } from './fetch-messages-from-graph.query';
import type { SyncDiagnosticsResult } from './sync-diagnostics.types';

@Injectable()
export class RunSyncDiagnosticsQuery {
  private logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
    private readonly fetchMessagesFromGraphQuery: FetchMessagesFromGraphQuery,
  ) {}

  @Span()
  public async run(userProfileId: string): Promise<SyncDiagnosticsResult> {
    try {
      return await this.runDiagnostics(userProfileId);
    } catch (error) {
      traceError(error);
      throw error;
    }
  }

  private async runDiagnostics(userProfileId: string): Promise<SyncDiagnosticsResult> {
    traceAttrs({ userProfileId });

    const userProfile = await this.db.query.userProfiles.findFirst({
      where: eq(userProfiles.id, userProfileId),
    });
    assert.ok(userProfile, `User profile not found: ${userProfileId}`);
    const { skipped, notSkipped } = await this.fetchMessagesFromGraphQuery.run({ userProfileId });

    const rootScope = await this.uniqueApi.scopes.getByExternalId(
      getRootScopeExternalIdForUser(userProfile.providerUserId),
    );
    assert.ok(rootScope, `Root scope not found for user: ${userProfileId}`);

    const uniqueKeys = await this.uniqueApi.files.getFileKeysByScopeId(rootScope.id);
    const uniqueKeySet = new Set(uniqueKeys);
    const allMicrosoftKeySet = new Set([
      ...skipped.map((e) => e.fileKey),
      ...notSkipped.map((e) => e.fileKey),
    ]);

    const messageIdsFoundInMicrosoftButNotFoundInUnique = notSkipped.filter(
      (e) => !uniqueKeySet.has(e.fileKey),
    );

    const messageIdsFoundInUniqueButNotFoundInMicrosoft = uniqueKeys
      .filter((key) => !allMicrosoftKeySet.has(key))
      .map((key) => {
        const match = key.match(/^MessageId:([^|]+)\|/);
        return { messageId: match?.[1] ?? key, fileKey: key };
      });

    const result: SyncDiagnosticsResult = {
      messageIdsSkippedBecauseOfFilters: skipped,
      messageIdsFoundInMicrosoftButNotFoundInUnique,
      messageIdsFoundInUniqueButNotFoundInMicrosoft,
    };

    this.logger.log({
      userProfileId: userProfile.id,
      providerUserId: userProfile.providerUserId,
      email: createSmeared(userProfile.email ?? '').toString(),
      ...result,
    });

    traceAttrs({
      skippedCount: result.messageIdsSkippedBecauseOfFilters.length,
      missingInUniqueCount: result.messageIdsFoundInMicrosoftButNotFoundInUnique.length,
      missingInMicrosoftCount: result.messageIdsFoundInUniqueButNotFoundInMicrosoft.length,
    });

    return result;
  }
}
