import { Activities, Activity } from '@unique-ag/temporal';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { Context } from '@temporalio/activity';
import { and, asc, eq } from 'drizzle-orm';
import {
  DRIZZLE,
  DrizzleDatabase,
  Email,
  emails as emailsTable,
} from '../../../drizzle';
import { LLMEmailCleanupService } from '../lib/llm-email-cleanup/llm-email-cleanup.service';
import { LLMSummarizationService } from '../lib/llm-summarization-service/llm-summarization.service';

export interface IProcessActivity {
  process(payload: ProcessPayload): Promise<void>;
}

interface ProcessPayload {
  userProfileId: string;
  emailId: string;
}

interface ProcessMetadata {
  emailId: string;
  userProfileId: string;
}

const SUMMARIZATION_THRESHOLD_CHARS = 1_600;

@Injectable()
@Activities()
export class ProcessActivity {
  private readonly logger = new Logger(this.constructor.name);
  
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly llmEmailCleanupService: LLMEmailCleanupService,
    private readonly llmSummarizationService: LLMSummarizationService,
  ) {}

  @Activity()
  public async process({ userProfileId, emailId }: ProcessPayload) {
    const contextInfo = Context.current().info;

    this.logger.debug({
      msg: "Processing email",
      emailId: emailId,
      userProfileId: userProfileId,
      attempt: contextInfo.attempt
    });

    const email = await this.db.query.emails.findFirst({
      where: and(
        eq(emailsTable.id, emailId),
        eq(emailsTable.userProfileId, userProfileId)
      ),
    });

    if (!email) {
      this.logger.warn("Email not found, skipping processing");
      return;
    }

    const { processedBody } = await this.cleanupBody(email, {
      emailId,
      userProfileId,
    });

    await this.summarizeBody(
      email,
      processedBody,
      {
        emailId,
        userProfileId,
      }
    );

    await this.summarizeThread(email, {
      emailId,
      userProfileId,
    });

    this.logger.debug({
      msg: "Email processed",
      emailId: emailId,
      userProfileId: userProfileId,
    });
  }

  private async cleanupBody(
    email: Email,
    options: ProcessMetadata
  ): Promise<{
    processedBody: string;
    language: string;
  }> {
    if (email.processedBody && email.language) {
      this.logger.log({
        msg: "Email body already cleaned, skipping",
        emailId: options.emailId,
        userProfileId: options.userProfileId,
      });
      return { processedBody: email.processedBody, language: email.language };
    }

    const {
      cleanMarkdown,
      meta: { language },
    } = await this.llmEmailCleanupService.cleanupEmail(email);

    await this.db
      .update(emailsTable)
      .set({
        processedBody: cleanMarkdown,
        language,
      })
      .where(
        and(
          eq(emailsTable.id, options.emailId),
          eq(emailsTable.userProfileId, options.userProfileId)
        )
      );
    return { processedBody: cleanMarkdown, language };
  }

  private async summarizeBody(
    email: Email,
    processedBody: string,
    options: ProcessMetadata
  ): Promise<string> {
    if (email.summarizedBody) {
      this.logger.log({
        msg: "Email already summarized, skipping",
        emailId: options.emailId,
        userProfileId: options.userProfileId,
      });
      return email.summarizedBody;
    }

    if (processedBody.length < SUMMARIZATION_THRESHOLD_CHARS) {
      this.logger.log({
        msg: "Processed body is too short, skipping summarization",
        emailId: options.emailId,
        userProfileId: options.userProfileId,
      });
      return processedBody;
    }

    const summarization = await this.llmSummarizationService.summarize(
      processedBody
    );

    await this.db
      .update(emailsTable)
      .set({
        summarizedBody: summarization.summarizedBody,
      })
      .where(
        and(
          eq(emailsTable.id, options.emailId),
          eq(emailsTable.userProfileId, options.userProfileId)
        )
      );

    return summarization.summarizedBody;
  }

  private async summarizeThread(
    email: Email,
    options: ProcessMetadata
  ): Promise<string | undefined> {
    if (email.threadSummary) {
      this.logger.log({
        msg: "Thread already summarized, skipping",
        emailId: options.emailId,
        userProfileId: options.userProfileId,
      });
      return email.threadSummary;
    }

    if (!email.conversationId) {
      this.logger.log({
        msg: "Email has no conversation ID, skipping thread summarization",
        emailId: options.emailId,
        userProfileId: options.userProfileId,
      });
      return;
    }

    const thread = await this.db.query.emails.findMany({
      where: and(
        eq(emailsTable.conversationId, email.conversationId),
        eq(emailsTable.userProfileId, email.userProfileId)
      ),
      orderBy: [asc(emailsTable.receivedAt)],
    });

    if (thread.length <= 1) {
      this.logger.log({
        msg: "Thread has only one email, skipping thread summarization",
        emailId: options.emailId,
        userProfileId: options.userProfileId,
      });
      return;
    }

    const threadText = thread.map((email) => email.processedBody).join("\n");
    const threadSummary = await this.llmSummarizationService.summarize(
      threadText
    );

    await this.db
      .update(emailsTable)
      .set({
        threadSummary: threadSummary.summarizedBody,
      })
      .where(
        and(
          eq(emailsTable.id, options.emailId),
          eq(emailsTable.userProfileId, options.userProfileId)
        )
      );
    return threadSummary.summarizedBody;
  }
}
