import { Activities, Activity } from '@unique-ag/temporal';
import { Injectable, Logger } from '@nestjs/common';
import { Context } from '@temporalio/activity';
import { LLMTranslationService } from '../lib/llm-translation-service/llm-translation.service';

export interface ITranslateActivity {
  translateEmail(payload: TranslatePayload): Promise<TranslateResult>;
}

interface TranslatePayload {
  emailId: string;
  subject: string | null;
  processedBody: string;
  language: string;
  translatedBody?: string | null;
  translatedSubject?: string | null;
}

interface TranslateResult {
  translatedBody: string;
  translatedSubject: string | null;
}

@Injectable()
@Activities()
export class TranslateActivity implements ITranslateActivity {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly llmTranslationService: LLMTranslationService) {}

  @Activity()
  public async translateEmail({
    emailId,
    subject,
    processedBody,
    language,
    translatedBody,
    translatedSubject,
  }: TranslatePayload): Promise<TranslateResult> {
    const contextInfo = Context.current().info;

    this.logger.debug({
      msg: 'Translating email',
      emailId,
      language,
      attempt: contextInfo.attempt,
    });

    if (language.toLowerCase() === 'en') {
      this.logger.log({
        msg: 'Email is already in English, skipping translation',
        emailId,
      });
      return { translatedBody: processedBody, translatedSubject: subject };
    }

    if (translatedBody && translatedSubject) {
      this.logger.log({
        msg: 'Email already translated, skipping',
        emailId,
      });
      return { translatedBody, translatedSubject };
    }

    const translation = await this.llmTranslationService.translate({
      subject,
      body: processedBody,
    });

    this.logger.debug({
      msg: 'Email translated',
      emailId,
      originalLanguage: language,
    });

    return {
      translatedBody: translation.body,
      translatedSubject: translation.subject,
    };
  }
}
