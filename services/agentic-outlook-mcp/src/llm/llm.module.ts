import { LangfuseClient } from '@langfuse/client';
import { Global, Module } from '@nestjs/common';
import { LangfusePromptService } from './langfuse-prompt.service';
import { LLMEmailCleanupService } from './lib/llm-email-cleanup/llm-email-cleanup.service';
import { LLMEmailTranslationService } from './lib/llm-email-translation-service/llm-email-translation.service';
import { LLMSummarizationService } from './lib/llm-summarization-service/llm-summarization.service';
import { LLMTranslationService } from './lib/llm-translation-service/llm-translation.service';
import { LLMService } from './llm.service';

@Global()
@Module({
  providers: [
    LLMService,
    LangfusePromptService,
    {
      provide: LangfuseClient,
      useValue: new LangfuseClient(),
    },
    LLMEmailCleanupService,
    LLMEmailTranslationService,
    LLMSummarizationService,
    LLMTranslationService,
  ],
  exports: [
    LLMService,
    LangfusePromptService,
    LangfuseClient,
    LLMEmailCleanupService,
    LLMEmailTranslationService,
    LLMSummarizationService,
    LLMTranslationService,
  ],
})
export class LLMModule {}
