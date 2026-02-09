import assert from 'node:assert';
import { createHash } from 'node:crypto';

import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span, TraceService } from 'nestjs-otel';

import { DRIZZLE, type DrizzleDatabase, subscriptions, syncedEmails, userProfiles } from '~/drizzle';
import { BatchResponse } from '~/email-sync/subscriptions/subscription.dtos';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UniqueService } from '~/unique/unique.service';
import {
  GRAPH_EMAIL_SELECT_FIELDS,
  type GraphEmail,
  GraphEmail as GraphEmailSchema,
  GraphMailFolder,
} from './email-sync.dtos';

const MESSAGE_ID_PATTERN = /messages\/(.+)$/;

@Injectable()
export class EmailSyncService {
  private readonly logger = new Logger(EmailSyncService.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly uniqueService: UniqueService,
    private readonly trace: TraceService,
  ) {}

  @Span()
  public async syncEmail(resource: string, subscriptionId: string): Promise<void> {
    const span = this.trace.getSpan();
    span?.setAttribute('subscription_id', subscriptionId);
    span?.setAttribute('resource', resource);

    this.logger.log(
      { subscriptionId, resource },
      'Starting email sync for notification resource',
    );

    const subscription = await this.db.query.subscriptions.findFirst({
      where: eq(subscriptions.subscriptionId, subscriptionId),
    });
    assert.ok(subscription, `Subscription not found for subscriptionId: ${subscriptionId}`);

    const userProfile = await this.db.query.userProfiles.findFirst({
      columns: { providerUserId: true, email: true },
      where: eq(userProfiles.id, subscription.userProfileId),
    });
    assert.ok(userProfile, `User profile not found for id: ${subscription.userProfileId}`);
    assert.ok(userProfile.email, `User profile ${subscription.userProfileId} has no email`);

    const { providerUserId, email: ownerEmail } = userProfile;
    span?.setAttribute('user_profile_id', subscription.userProfileId);
    span?.setAttribute('provider_user_id', providerUserId);

    const messageId = this.parseMessageId(resource);
    span?.setAttribute('message_id', messageId);

    this.logger.debug(
      { messageId, providerUserId },
      'Parsed message ID from notification resource',
    );

    const client = this.graphClientFactory.createClientForUser(subscription.userProfileId);

    const batchPayload = {
      requests: [
        {
          id: 'email',
          method: 'GET',
          url: `/users/${providerUserId}/messages/${messageId}?$select=${GRAPH_EMAIL_SELECT_FIELDS}`,
          headers: { Prefer: 'IdType="ImmutableId"' },
        },
        {
          id: 'deletedItems',
          method: 'GET',
          url: `/users/${providerUserId}/mailFolders/deleteditems?$select=id`,
          headers: { Prefer: 'IdType="ImmutableId"' },
        },
      ],
    };

    const batchResponse = (await client.api('/$batch').post(batchPayload)) as unknown;
    const parsed = BatchResponse.parse(batchResponse);

    const emailResponse = parsed.responses.find((r) => r.id === 'email');
    const deletedItemsResponse = parsed.responses.find((r) => r.id === 'deletedItems');
    assert.ok(emailResponse, 'Batch response missing email response');
    assert.ok(deletedItemsResponse, 'Batch response missing deletedItems response');

    if (emailResponse.status === 404) {
      span?.addEvent('email_not_found_at_source');
      this.logger.log({ messageId }, 'Email not found at source (404), processing deletion');
      await this.handleDeletedEmail(messageId);
      return;
    }

    assert.ok(
      emailResponse.status === 200,
      `Unexpected email batch response status: ${emailResponse.status}`,
    );
    assert.ok(
      deletedItemsResponse.status === 200,
      `Unexpected deleted items batch response status: ${deletedItemsResponse.status}`,
    );

    const email = GraphEmailSchema.parse(emailResponse.body);
    const deletedItemsFolder = GraphMailFolder.parse(deletedItemsResponse.body);

    span?.setAttribute('email_subject', email.subject ?? '');
    span?.setAttribute('is_draft', email.isDraft);

    if (email.parentFolderId === deletedItemsFolder.id) {
      span?.addEvent('email_in_deleted_items');
      this.logger.log({ messageId }, 'Email is in deleted items folder, processing deletion');
      await this.handleDeletedEmail(email.id);
      return;
    }

    const cachedEmail = await this.db.query.syncedEmails.findFirst({
      where: eq(syncedEmails.emailId, email.id),
    });

    const contentHash = this.computeContentHash(email);

    if (cachedEmail && cachedEmail.contentHash === contentHash && !email.isDraft) {
      span?.addEvent('email_unchanged_skipping');
      this.logger.debug(
        { messageId, emailId: email.id },
        'Email content unchanged and not a draft, skipping sync',
      );
      return;
    }

    const emlStream = (await client
      .api(`/users/${providerUserId}/messages/${messageId}/$value`)
      .getStream()) as ReadableStream<Uint8Array<ArrayBuffer>>;

    const metadata = this.buildEmailMetadata(email);

    const { scopeId } = await this.uniqueService.ingestEmail(ownerEmail, {
      key: email.id,
      subject: email.subject ?? '',
      content: emlStream,
      metadata,
    });

    span?.setAttribute('scope_id', scopeId);
    span?.addEvent('email_ingested', { emailId: email.id, scopeId });

    await this.db
      .insert(syncedEmails)
      .values({
        emailId: email.id,
        contentHash,
        scopeId,
        contentKey: email.id,
        internetMessageId: email.internetMessageId ?? '',
        userProfileId: subscription.userProfileId,
      })
      .onConflictDoUpdate({
        target: syncedEmails.emailId,
        set: {
          contentHash,
          scopeId,
          contentKey: email.id,
          internetMessageId: email.internetMessageId ?? '',
          updatedAt: new Date(),
        },
      });

    this.logger.log(
      { messageId, emailId: email.id, scopeId },
      'Successfully synced email to knowledge base',
    );
  }

  @Span()
  private async handleDeletedEmail(emailId: string): Promise<void> {
    const span = this.trace.getSpan();

    const cachedEmail = await this.db.query.syncedEmails.findFirst({
      where: eq(syncedEmails.emailId, emailId),
    });

    if (!cachedEmail) {
      span?.addEvent('no_cached_email_for_deletion');
      this.logger.debug(
        { emailId },
        'No cached email found for deletion, nothing to remove',
      );
      return;
    }

    await this.uniqueService.deleteContent(cachedEmail.contentKey, cachedEmail.scopeId);
    await this.db.delete(syncedEmails).where(eq(syncedEmails.emailId, emailId));

    span?.addEvent('email_deleted_from_kb', {
      emailId,
      scopeId: cachedEmail.scopeId,
    });

    this.logger.log(
      { emailId, scopeId: cachedEmail.scopeId },
      'Successfully deleted email from knowledge base and cache',
    );
  }

  private parseMessageId(resource: string): string {
    const match = MESSAGE_ID_PATTERN.exec(resource);
    assert.ok(match?.[1], `Cannot parse messageId from resource: ${resource}`);
    return match[1];
  }

  private computeContentHash(email: GraphEmail): string {
    const parts = [
      email.from?.emailAddress.address ?? '',
      email.subject ?? '',
    ];
    return createHash('sha256').update(parts.join('|')).digest('hex');
  }

  private buildEmailMetadata(email: GraphEmail): Record<string, string> {
    return {
      subject: email.subject ?? '',
      from: email.from?.emailAddress.address ?? '',
      to: email.toRecipients.map((r) => r.emailAddress.address).join(', '),
      cc: email.ccRecipients.map((r) => r.emailAddress.address).join(', '),
      date: email.receivedDateTime ?? '',
      conversationId: email.conversationId ?? '',
      conversationIndex: email.conversationIndex ?? '',
      hasAttachments: String(email.hasAttachments),
      isDraft: String(email.isDraft),
      importance: email.importance,
    };
  }
}
