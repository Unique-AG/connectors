import { Activities, Activity } from '@unique-ag/temporal';
import { Injectable, Logger } from '@nestjs/common';
import { Context } from '@temporalio/activity';
import { LLMSummarizationService } from '../lib/llm-summarization-service/llm-summarization.service';

export interface ISummarizeBodyActivity {
  summarizeBody(payload: SummarizeBodyPayload): Promise<SummarizeBodyResult>;
}

interface SummarizeBodyPayload {
  emailId: string;
  translatedBody: string;
  summarizedBody?: string | null;
}

interface SummarizeBodyResult {
  summarizedBody: string | null;
}

const SUMMARIZATION_THRESHOLD_CHARS = 1_600;

@Injectable()
@Activities()
export class SummarizeBodyActivity implements ISummarizeBodyActivity {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly llmSummarizationService: LLMSummarizationService) {}

  @Activity()
  public async summarizeBody({
    emailId,
    translatedBody,
    summarizedBody,
  }: SummarizeBodyPayload): Promise<SummarizeBodyResult> {
    const contextInfo = Context.current().info;

    this.logger.debug({
      msg: 'Summarizing email body',
      emailId,
      attempt: contextInfo.attempt,
    });

    if (summarizedBody) {
      this.logger.log({
        msg: 'Email already summarized, skipping',
        emailId,
      });
      return { summarizedBody };
    }

    if (translatedBody.length < SUMMARIZATION_THRESHOLD_CHARS) {
      this.logger.log({
        msg: 'Processed body is too short, skipping summarization',
        emailId,
        bodyLength: translatedBody.length,
      });
      return { summarizedBody: null };
    }

    const summarization = await this.llmSummarizationService.summarize(translatedBody);

    this.logger.debug({
      msg: 'Email body summarized',
      emailId,
    });

    return { summarizedBody: summarization.summarizedBody };
  }
}
