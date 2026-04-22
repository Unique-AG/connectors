import assert from 'node:assert';
import { UniqueApiClient } from '@unique-ag/unique-api';
import { createSmeared } from '@unique-ag/utils';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { DRIZZLE, DrizzleDatabase, directories, inboxConfigurations, userProfiles } from '~/db';
import {
  InboxConfigurationMailFilters,
  inboxConfigurationMailFilters,
} from '~/db/schema/inbox/inbox-configuration-mail-filters.dto';
import {
  GraphMessage,
  GraphMessageFields,
  graphMessagesResponseSchema,
} from '~/features/process-email/dtos/microsoft-graph.dtos';
import { getUniqueKeyForMessage } from '~/features/process-email/utils/get-unique-key-for-message';
import { shouldSkipEmail } from '~/features/process-email/utils/should-skip-email';
import { traceAttrs, traceError } from '~/features/tracing.utils';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { getRootScopeExternalIdForUser } from '~/unique/get-root-scope-path';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { computeRetentionCutoffDate } from '~/utils/date/compute-retention-cutoff-date';
import type { EmailDiagnosticEntry, SyncDiagnosticsResult } from './sync-diagnostics.types';

@Injectable()
export class RunSyncDiagnosticsQuery {
  private logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
    private readonly graphClientFactory: GraphClientFactory,
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
    const userEmail = userProfile.email;
    assert.ok(userEmail, `User profile has no email: ${userProfileId}`);

    const config = await this.db.query.inboxConfigurations.findFirst({
      where: eq(inboxConfigurations.userProfileId, userProfileId),
    });
    assert.ok(config, `Inbox config not found for user: ${userProfileId}`);

    const filters = inboxConfigurationMailFilters.parse(config.filters);
    const cutoff = computeRetentionCutoffDate(filters.retentionWindowInDays);
    const graphFilter = `receivedDateTime ge ${cutoff.toISOString()}`;

    const client = this.graphClientFactory.createClientForUser(userProfileId);

    let response = graphMessagesResponseSchema.parse(
      await client
        .api('me/messages')
        .header('Prefer', 'IdType="ImmutableId"')
        .select(GraphMessageFields)
        .filter(graphFilter)
        .orderby('receivedDateTime asc')
        .top(999)
        .get(),
    );

    const ignoredDirectories = await this.db.query.directories.findMany({
      where: and(
        eq(directories.userProfileId, userProfileId),
        eq(directories.ignoreForSync, true),
      ),
    });
    const ignoredFolderIdSet = new Set(ignoredDirectories.map((d) => d.providerDirectoryId));

    const skipped: EmailDiagnosticEntry[] = [];
    const notSkipped: EmailDiagnosticEntry[] = [];

    this.processMessages({
      userEmail: userEmail,
      messages: response.value,
      userProfileId: userProfile.id,
      filters,
      ignoredFolderIdSet,
      skipped,
      notSkipped,
    });

    while (response['@odata.nextLink']) {
      response = graphMessagesResponseSchema.parse(
        await client
          .api(response['@odata.nextLink'])
          .header('Prefer', 'IdType="ImmutableId"')
          .get(),
      );
      this.processMessages({
        userEmail: userEmail,
        messages: response.value,
        userProfileId: userProfile.id,
        filters,
        ignoredFolderIdSet,
        skipped,
        notSkipped,
      });
    }

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

  private processMessages({
    userEmail,
    userProfileId,
    messages,
    skipped,
    notSkipped,
    filters,
    ignoredFolderIdSet,
  }: {
    userEmail: string;
    messages: GraphMessage[];
    skipped: EmailDiagnosticEntry[];
    notSkipped: EmailDiagnosticEntry[];
    userProfileId: string;
    filters: InboxConfigurationMailFilters;
    ignoredFolderIdSet: Set<string>;
  }): void {
    for (const message of messages) {
      const fileKey = getUniqueKeyForMessage({
        userEmail: userEmail,
        messageId: message.id,
      });
      const skipResult = shouldSkipEmail(message, filters, { userProfileId });
      if (skipResult.skip || ignoredFolderIdSet.has(message.parentFolderId)) {
        skipped.push({ messageId: message.id, fileKey });
      } else {
        notSkipped.push({ messageId: message.id, fileKey });
      }
    }
  }
}
