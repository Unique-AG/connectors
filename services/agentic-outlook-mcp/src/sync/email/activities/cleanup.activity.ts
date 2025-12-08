import { Activities, Activity } from '@unique-ag/temporal';
import { Injectable, Logger } from '@nestjs/common';
import { Context } from '@temporalio/activity';
import { Email } from '../../../drizzle';
import { LLMEmailCleanupService } from '../../../llm';

export interface ICleanupActivity {
  cleanupEmail(payload: CleanupPayload): Promise<CleanupResult>;
}

interface CleanupPayload {
  email: Email;
}

interface CleanupResult {
  processedBody: string;
  language: string;
}

@Injectable()
@Activities()
export class CleanupActivity implements ICleanupActivity {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly llmEmailCleanupService: LLMEmailCleanupService) {}

  @Activity()
  public async cleanupEmail({ email }: CleanupPayload): Promise<CleanupResult> {
    const contextInfo = Context.current().info;

    this.logger.debug({
      msg: 'Cleaning up email',
      emailId: email.id,
      attempt: contextInfo.attempt,
    });

    if (email.processedBody && email.language) {
      this.logger.log({
        msg: 'Email already cleaned, skipping',
        emailId: email.id,
      });
      return { processedBody: email.processedBody, language: email.language };
    }

    const {
      cleanMarkdown,
      meta: { language },
    } = await this.llmEmailCleanupService.cleanupEmail(email);

    this.logger.debug({
      msg: 'Email cleaned up',
      emailId: email.id,
      language,
    });

    return { processedBody: cleanMarkdown, language };
  }
}
