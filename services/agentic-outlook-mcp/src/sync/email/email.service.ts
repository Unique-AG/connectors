import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq, inArray, sql } from 'drizzle-orm';
import { TypeID } from 'typeid-js';
import { DRIZZLE, DrizzleDatabase, EmailInput, emails as emailsTable } from '../../drizzle';

@Injectable()
export class EmailService {
  private readonly logger = new Logger(EmailService.name);

  public constructor(@Inject(DRIZZLE) private readonly db: DrizzleDatabase) {}

  public async upsertEmail(
    userProfileId: TypeID<'user_profile'>,
    folderId: string,
    email: EmailInput,
  ): Promise<TypeID<'email'>> {

    const result = await this.db
      .insert(emailsTable)
      .values(
        ({
          ...email,
          userProfileId: userProfileId.toString(),
          folderId,
        }),
      )
      .onConflictDoUpdate({
        target: emailsTable.messageId,
        set: {
          conversationId: sql`excluded.conversation_id`,
          internetMessageId: sql`excluded.internet_message_id`,
          webLink: sql`excluded.web_link`,
          version: sql`excluded.version`,
          from: sql`excluded.from`,
          sender: sql`excluded.sender`,
          replyTo: sql`excluded.reply_to`,
          to: sql`excluded.to`,
          cc: sql`excluded.cc`,
          bcc: sql`excluded.bcc`,
          sentAt: sql`excluded.sent_at`,
          receivedAt: sql`excluded.received_at`,
          subject: sql`excluded.subject`,
          preview: sql`excluded.preview`,
          bodyText: sql`excluded.body_text`,
          bodyHtml: sql`excluded.body_html`,
          uniqueBodyText: sql`excluded.unique_body_text`,
          uniqueBodyHtml: sql`excluded.unique_body_html`,
          processedBody: sql`excluded.processed_body`,
          isRead: sql`excluded.is_read`,
          isDraft: sql`excluded.is_draft`,
          sizeBytes: sql`excluded.size_bytes`,
          tags: sql`excluded.tags`,
          hasAttachments: sql`excluded.has_attachments`,
          attachments: sql`excluded.attachments`,
          attachmentCount: sql`excluded.attachment_count`,
          headers: sql`excluded.headers`,
          ingestionStatus: sql`excluded.ingestion_status`,
          ingestionLastError: sql`excluded.ingestion_last_error`,
          ingestionLastAttemptAt: sql`excluded.ingestion_last_attempt_at`,
          ingestionCompletedAt: sql`excluded.ingestion_completed_at`,
        },
      }).returning({ id: emailsTable.id });

    const [savedEmail] = result;
    if (!savedEmail) throw new Error('Failed to upsert email');

    return TypeID.fromString(savedEmail.id, 'email');
  }

  public async deleteEmails(
    userProfileId: TypeID<'user_profile'>,
    messageIds: string[],
  ): Promise<void> {
    if (!messageIds.length) return;

    await this.db
      .delete(emailsTable)
      .where(
        and(
          eq(emailsTable.userProfileId, userProfileId.toString()),
          inArray(emailsTable.messageId, messageIds),
        ),
      );

    this.logger.debug({
      msg: 'Deleted emails',
      count: messageIds.length,
      userProfileId: userProfileId.toString(),
    });
  }
}
