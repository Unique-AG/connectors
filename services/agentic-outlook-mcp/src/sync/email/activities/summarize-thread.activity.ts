import { Activities, Activity } from '@unique-ag/temporal';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { Context } from '@temporalio/activity';
import { and, asc, eq } from 'drizzle-orm';
import { DRIZZLE, DrizzleDatabase, Email, emails as emailsTable } from '../../../drizzle';
import { LLMSummarizationService } from '../../../llm';

export interface ISummarizeThreadActivity {
  summarizeThread(payload: SummarizeThreadPayload): Promise<SummarizeThreadResult | null>;
}

interface SummarizeThreadPayload {
  email: Email;
}

interface SummarizeThreadResult {
  threadSummary: string;
}

@Injectable()
@Activities()
export class SummarizeThreadActivity implements ISummarizeThreadActivity {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly llmSummarizationService: LLMSummarizationService,
  ) {}

  @Activity()
  public async summarizeThread({
    email,
  }: SummarizeThreadPayload): Promise<SummarizeThreadResult | null> {
    const contextInfo = Context.current().info;

    this.logger.debug({
      msg: 'Summarizing email thread',
      emailId: email.id,
      attempt: contextInfo.attempt,
    });

    if (email.threadSummary) {
      this.logger.log({
        msg: 'Thread already summarized, skipping',
        emailId: email.id,
      });
      return { threadSummary: email.threadSummary };
    }

    if (!email.conversationId) {
      this.logger.log({
        msg: 'Email has no conversation ID, skipping thread summarization',
        emailId: email.id,
      });
      return null;
    }

    const thread = await this.db.query.emails.findMany({
      where: and(
        eq(emailsTable.conversationId, email.conversationId),
        eq(emailsTable.userProfileId, email.userProfileId),
      ),
      orderBy: [asc(emailsTable.receivedAt)],
    });

    if (thread.length <= 1) {
      this.logger.log({
        msg: 'Thread has only one email, skipping thread summarization',
        emailId: email.id,
      });
      return null;
    }

    const threadText = thread.map((email) => email.processedBody).join('\n');
    const threadSummary = await this.llmSummarizationService.summarize(threadText);

    this.logger.debug({
      msg: 'Email thread summarized',
      emailId: email.id,
      threadLength: thread.length,
    });

    return { threadSummary: threadSummary.summarizedBody };
  }
}
