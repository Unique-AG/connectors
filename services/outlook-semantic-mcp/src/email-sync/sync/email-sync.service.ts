import assert from 'node:assert';
import { createHash } from 'node:crypto';

import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span, TraceService } from 'nestjs-otel';

import { DRIZZLE, type DrizzleDatabase, subscriptions, syncedEmails, UserProfile, userProfiles } from '~/drizzle';
import { BatchResponse } from '~/email-sync/subscriptions/subscription.dtos';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UniqueService } from '~/unique/unique.service';
import {
  GRAPH_EMAIL_SELECT_FIELDS,
  GraphEmail,
} from './email-sync.dtos';
import { GetUserEmailFolderStructureQuery } from './get-user-email-folder-structure.query';
import { GraphDirectoryStructureUtil } from './directory-structure-util';
import { Client } from '@microsoft/microsoft-graph-client';
import { DeleteInjestedEmailCommand } from './delete-ingested-email.command';

@Injectable()
export class EmailSyncService {
  private readonly logger = new Logger(EmailSyncService.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly uniqueService: UniqueService,
    private readonly trace: TraceService,
    private readonly getUserEmailFolderStructureQuery: GetUserEmailFolderStructureQuery,
    private readonly deleteInjestedEmailCommand: DeleteInjestedEmailCommand,
  ) {}

  @Span()
  public async syncEmail(
    messageId: string, 
    subscriptionId: string
  ): Promise<void> {
    const span = this.trace.getSpan();
    span?.setAttribute('subscription_id', subscriptionId);
    span?.setAttribute('message_id', messageId);

    this.logger.log(
      { subscriptionId, messageId },
      'Starting email sync for notification resource',
    );

    const subscription = await this.db.query.subscriptions.findFirst({
      where: eq(subscriptions.subscriptionId, subscriptionId),
    });
    assert.ok(subscription, `Subscription not found for subscriptionId: ${subscriptionId}`);

    const userProfile = await this.db.query.userProfiles.findFirst({
      where: eq(userProfiles.id, subscription.userProfileId),
    });
    assert.ok(userProfile, `User profile not found for id: ${subscription.userProfileId}`);
    assert.ok(userProfile.email, `User profile ${subscription.userProfileId} has no email`);

    const { providerUserId, email: ownerEmail } = userProfile;
    span?.setAttribute('user_profile_id', subscription.userProfileId);
    span?.setAttribute('provider_user_id', providerUserId);

    const client = this.graphClientFactory.createClientForUser(subscription.userProfileId);
    // TODO -> Read this from db
    let currentFolderStructure = await this.getUserEmailFolderStructureQuery.run({userInfo: userProfile, client});
    
    const messageResponse = await client.api(`/users/${providerUserId}/messages/${messageId}?$select=${GRAPH_EMAIL_SELECT_FIELDS}`)
    .header(`Prefer`, `IdType="ImmutableId"`)
    .get();
    const email = GraphEmail.parse(messageResponse);

    span?.setAttribute('email_subject', email.subject ?? '');
    span?.setAttribute('is_draft', email.isDraft);

    if (!currentFolderStructure.has(email.parentFolderId)) {
      currentFolderStructure = await this.processNewFolderStructure({currentFolderStructure, userProfile, client})
    }

    const knowledgeBaseEmailKey = this.getKeyForEmail(userProfile.email, email);

    if (!currentFolderStructure.isSyncronizedDyrectory(email.parentFolderId)) {
      await this.deleteInjestedEmailCommand.run(knowledgeBaseEmailKey);
      return;
    }

    const metadata = this.buildEmailMetadata(email);

    const doesFileExist = await this.uniqueService.getFilesByKeys([knowledgeBaseEmailKey]);
    if (doesFileExist.length == 0) {
      await this.uniqueService. 
    }
    // const cachedEmail = await this.db.query.syncedEmails.findFirst({
    //   where: eq(syncedEmails.emailId, email.id),
    // });

    // const contentHash = this.computeContentHash(email);

    // if (cachedEmail && cachedEmail.contentHash === contentHash && !email.isDraft) {
    //   span?.addEvent('email_unchanged_skipping');
    //   this.logger.debug(
    //     { messageId, emailId: email.id },
    //     'Email content unchanged and not a draft, skipping sync',
    //   );
    //   return;
    // }

    const emlStream = (await client
      .api(`/users/${providerUserId}/messages/${messageId}/$value`)
      .getStream()) as ReadableStream<Uint8Array<ArrayBuffer>>;


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

  private computeContentHash(email: GraphEmail): string {
    const parts = [
      email.from?.emailAddress.address ?? '',
      email.subject ?? '',
      email.uniqueBody?.content
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

  private async processNewFolderStructure({currentFolderStructure, userProfile, client}: {
    currentFolderStructure: GraphDirectoryStructureUtil;
    userProfile:UserProfile;
    client: Client;
}): Promise<GraphDirectoryStructureUtil> {
    const newFolderStructure = await this.getUserEmailFolderStructureQuery.run({userInfo: userProfile, client});

    if (!newFolderStructure.isSyncronizedDirectoryStructuralyEqual(currentFolderStructure)) {
      // The syncronized directories are changed we need to do a full sync
    } else if (newFolderStructure.isSyncronizedDirectoryEqual(currentFolderStructure)) {
      // The syncronized directories are structuraly the same but their names difer so we need to do scope renaming
    }
    return newFolderStructure
 }

 private getKeyForEmail(currentUserEmail: string, email: GraphEmail): string {
  if (email.internetMessageId) {
    return [`From:${currentUserEmail}`,`InternetId:${email.internetMessageId ?? ''}`].join(`_`);
  }
  const parts = [
    email.from?.emailAddress.address ?? '',
    email.subject ?? '',
    email.uniqueBody?.content
  ];
  const contentHash = createHash('sha256').update(parts.join('|')).digest('hex');
  return [`From:${currentUserEmail}`,`ContentHash:${contentHash}`].join('_');
 }
}
