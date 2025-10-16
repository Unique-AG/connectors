import { observeOpenAI } from '@langfuse/openai';
import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import OpenAI from 'openai';
import { AppConfig, AppSettings } from '../app-settings';

@Injectable()
export class LLMService {
  public readonly client: OpenAI;

  public constructor(configService: ConfigService<AppConfig, true>) {
    const client = observeOpenAI(
      new OpenAI({
        apiKey: configService.get(AppSettings.LITELLM_API_KEY),
        baseURL: configService.get(AppSettings.LITELLM_BASE_URL),
      }),
    );
    this.client = client;
  }
}
