import assert from 'node:assert';
import { Inject, Injectable } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { isNonNullish, isNullish, unique } from 'remeda';
import z from 'zod/v4';
import { DRIZZLE, DrizzleDatabase, directories, inboxConfigurations, userProfiles } from '~/db';
import {
  InboxConfigurationMailFilters,
  inboxConfigurationMailFilters,
} from '~/db/schema/inbox/inbox-configuration-mail-filters.dto';
import { getUniqueKeyForMessage } from '~/features/process-email/utils/get-unique-key-for-message';
import { shouldSkipEmail } from '~/features/process-email/utils/should-skip-email';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { computeRetentionCutoffDate } from '~/utils/date/compute-retention-cutoff-date';
import type { EmailDiagnosticEntry } from './sync-diagnostics.types';

const fetchMessageSchema = z.object({
  id: z.string(),
  parentFolderId: z.string(),
  receivedDateTime: z.string(),
  from: z
    .object({ emailAddress: z.object({ address: z.string().optional() }).optional().nullable() })
    .optional()
    .nullable(),
  subject: z.string().optional().nullable(),
  uniqueBody: z.object({ content: z.string().optional() }).optional().nullable(),
});

type FetchMessage = z.infer<typeof fetchMessageSchema>;

const fetchMessageFields: (keyof FetchMessage)[] = [
  'id',
  'parentFolderId',
  'receivedDateTime',
  'from',
  'subject',
  'uniqueBody',
];

const fetchMessagesResponseSchema = z.object({
  '@odata.nextLink': z.string().optional(),
  value: z.array(fetchMessageSchema),
});

const translateIdsResponseSchema = z.object({
  value: z.array(z.object({ sourceId: z.string(), targetId: z.string() })),
});

interface FetchMessagesFromGraphInput {
  userProfileId: string;
  filter?: string;
  search?: string;
}

interface FetchMessagesFromGraphResult {
  skipped: EmailDiagnosticEntry[];
  notSkipped: EmailDiagnosticEntry[];
  userEmail: string;
}

@Injectable()
export class FetchMessagesFromGraphQuery {
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly graphClientFactory: GraphClientFactory,
  ) {}

  @Span()
  public async run(input: FetchMessagesFromGraphInput): Promise<FetchMessagesFromGraphResult> {
    const { userProfileId, filter, search } = input;
    if (filter) {
      assert.ok(isNullish(search), `We can only use eigter search or filter`);
    }
    if (search) {
      assert.ok(isNullish(filter), `We can only use eigter search or filter`);
    }

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

    const client = this.graphClientFactory.createClientForUser(userProfileId);

    const cutoff = computeRetentionCutoffDate(filters.retentionWindowInDays);

    // $search and $filter cannot be combined on the messages endpoint; when search is provided
    // we skip the filter entirely (including the retention cutoff).
    let apiCall = client.api('me/messages').select(fetchMessageFields).top(999);

    if (!search) {
      const filtersList = [`receivedDateTime ge ${cutoff.toISOString()}`];
      if (filter) {
        filtersList.push(`(${filter})`);
      }
      apiCall = apiCall
        .filter(`(${filtersList.join(' and ')})`)
        .header('Prefer', 'IdType="ImmutableId"');
    } else {
      apiCall = apiCall.search(search);
    }

    // Collect all pages before processing so we can bulk-translate IDs when using $search.
    const allMessages: FetchMessage[] = [];

    let response = fetchMessagesResponseSchema.parse(await apiCall.get());
    allMessages.push(...response.value);

    while (response['@odata.nextLink']) {
      const nextCall = client.api(response['@odata.nextLink']);
      if (!search) {
        nextCall.header('Prefer', 'IdType="ImmutableId"');
      }
      response = fetchMessagesResponseSchema.parse(await nextCall.get());
      allMessages.push(...response.value);
    }

    if (search) {
      await this.translateToImmutableIds(client, allMessages);
    }

    const ignoredDirectories = await this.db.query.directories.findMany({
      where: and(eq(directories.userProfileId, userProfileId), eq(directories.ignoreForSync, true)),
    });
    const ignoredFolderIdSet = new Set(ignoredDirectories.map((d) => d.providerDirectoryId));

    const skipped: EmailDiagnosticEntry[] = [];
    const notSkipped: EmailDiagnosticEntry[] = [];

    this.processMessages({
      userEmail,
      messages: allMessages,
      userProfileId: userProfile.id,
      filters,
      ignoredFolderIdSet,
      skipped,
      notSkipped,
    });

    return { skipped, notSkipped, userEmail };
  }

  private async translateToImmutableIds(
    client: ReturnType<GraphClientFactory['createClientForUser']>,
    messages: FetchMessage[],
  ): Promise<void> {
    if (messages.length === 0) {
      return;
    }

    const folderIds = unique(
      messages.map((message) => message.parentFolderId).filter(isNonNullish),
    );
    const folderIdToImmutableFolderId = new Map<string, string>();

    const CHUNK_SIZE = 1000;
    for (let i = 0; i < folderIds.length; i += CHUNK_SIZE) {
      const inputIds = folderIds.slice(i, i + CHUNK_SIZE);
      const raw = await client.api('me/translateExchangeIds').post({
        inputIds,
        sourceIdType: 'restId',
        targetIdType: 'restImmutableEntryId',
      });
      const { value } = translateIdsResponseSchema.parse(raw);
      value.forEach((item) => {
        folderIdToImmutableFolderId.set(item.sourceId, item.targetId);
      });
    }

    for (let i = 0; i < messages.length; i += CHUNK_SIZE) {
      const chunk = messages.slice(i, i + CHUNK_SIZE);
      const raw = await client.api('me/translateExchangeIds').post({
        inputIds: unique(messages.slice(i, i + CHUNK_SIZE).map((item) => item.id)),
        sourceIdType: 'restId',
        targetIdType: 'restImmutableEntryId',
      });
      const { value } = translateIdsResponseSchema.parse(raw);
      const messageIdToImmutableMessageId = new Map(
        value.map(({ sourceId, targetId }) => [sourceId, targetId]),
      );
      for (const message of chunk) {
        const immutableId = messageIdToImmutableMessageId.get(message.id);
        if (immutableId) {
          message.id = immutableId;
        }
        const immutableParentFolderId = message.parentFolderId
          ? folderIdToImmutableFolderId.get(message.parentFolderId)
          : null;

        if (immutableParentFolderId) {
          message.parentFolderId = immutableParentFolderId;
        }
      }
    }
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
    messages: FetchMessage[];
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
        notSkipped.push({ messageId: message.id, fileKey, parentFolderId: message.parentFolderId });
      }
    }
  }
}
