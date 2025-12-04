import { InjectTemporalClient } from '@unique-ag/temporal';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { WorkflowClient } from '@temporalio/client';
import { and, eq, inArray, sql } from 'drizzle-orm';
import { TypeID, typeid } from 'typeid-js';
import { DRIZZLE, DrizzleDatabase, EmailInput, emails as emailsTable } from '../../drizzle';

@Injectable()
export class EmailService {
  private readonly logger = new Logger(EmailService.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @InjectTemporalClient() private readonly temporalClient: WorkflowClient,
  ) {}

  public async upsertEmail(
    userProfileId: TypeID<'user_profile'>,
    folderId: string,
    email: EmailInput,
  ): Promise<TypeID<'email'>> {
    const result = await this.db
      .insert(emailsTable)
      .values({
        ...email,
        userProfileId: userProfileId.toString(),
        folderId,
      })
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
          isRead: sql`excluded.is_read`,
          isDraft: sql`excluded.is_draft`,
          tags: sql`excluded.tags`,
          hasAttachments: sql`excluded.has_attachments`,
          attachments: sql`excluded.attachments`,
          attachmentCount: sql`excluded.attachment_count`,
          headers: sql`excluded.headers`,
        },
      })
      .returning({ id: emailsTable.id });

    const [savedEmail] = result;
    if (!savedEmail) throw new Error('Failed to upsert email');

    return TypeID.fromString(savedEmail.id, 'email');
  }

  public async deleteEmails(
    userProfileId: TypeID<'user_profile'>,
    messageIds: string[],
  ): Promise<TypeID<'email'>[]> {
    if (!messageIds.length) return [];

    const result = await this.db
      .delete(emailsTable)
      .where(
        and(
          eq(emailsTable.userProfileId, userProfileId.toString()),
          inArray(emailsTable.messageId, messageIds),
        ),
      )
      .returning({ id: emailsTable.id });

    this.logger.debug({
      msg: 'Deleted emails',
      count: messageIds.length,
      userProfileId: userProfileId.toString(),
    });

    return result.map((row) => TypeID.fromString(row.id, 'email'));
  }

  public async reprocessEmail(userProfileId: TypeID<'user_profile'>, emailId: TypeID<'email'>) {
    this.logger.log({ msg: 'Reprocessing email', userProfileId, emailId });

    const email = await this.db.query.emails.findFirst({
      where: and(
        eq(emailsTable.id, emailId.toString()),
        eq(emailsTable.userProfileId, userProfileId.toString()),
      ),
    });

    if (!email) throw new Error(`Email not found: ${emailId}`);

    const workflowId = `wf-reprocess-${emailId.toString()}-${typeid()}`;

    const handle = await this.temporalClient.start('ingest', {
      args: [{ userProfileId: userProfileId.toString(), emailId: emailId.toString() }],
      taskQueue: 'default',
      workflowId,
    });

    this.logger.log({
      msg: 'Started reprocess workflow',
      workflowId: handle.workflowId,
      userProfileId,
      emailId,
    });
  }
}
