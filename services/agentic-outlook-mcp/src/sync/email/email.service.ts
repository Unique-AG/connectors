import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq, inArray, sql } from 'drizzle-orm';
import { TypeID } from 'typeid-js';
import { DRIZZLE, DrizzleDatabase, EmailInput, emails as emailsTable } from '../../drizzle';

@Injectable()
export class EmailService {
  private readonly logger = new Logger(EmailService.name);

  public constructor(@Inject(DRIZZLE) private readonly db: DrizzleDatabase) {}

  public async upsertEmails(
    userProfileId: TypeID<'user_profile'>,
    folderId: string,
    emails: EmailInput[],
  ): Promise<void> {
    if (!emails.length) return;

    await this.db
      .insert(emailsTable)
      .values(
        emails.map((email) => ({
          ...email,
          userProfileId: userProfileId.toString(),
          folderId,
        })),
      )
      .onConflictDoUpdate({
        target: emailsTable.messageId,
        set: {
          conversationId: sql`excluded.conversation_id`,
          internetMessageId: sql`excluded.internet_message_id`,
          webLink: sql`excluded.web_link`,
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
          isRead: sql`excluded.is_read`,
          isDraft: sql`excluded.is_draft`,
          sizeBytes: sql`excluded.size_bytes`,
          tags: sql`excluded.tags`,
          attachments: sql`excluded.attachments`,
          attachmentCount: sql`excluded.attachment_count`,
          headers: sql`excluded.headers`,
          updatedAt: sql`NOW()`,
        },
      });

    this.logger.debug({
      msg: 'Upserted emails',
      count: emails.length,
      folderId,
      userProfileId: userProfileId.toString(),
    });
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
