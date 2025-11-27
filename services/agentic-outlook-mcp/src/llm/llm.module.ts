import { LangfuseClient } from '@langfuse/client';
import { Global, Module } from '@nestjs/common';
import { LangfusePromptService } from './langfuse-prompt.service';
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
  ],
  exports: [LLMService, LangfusePromptService, LangfuseClient],
})
export class LLMModule {}
