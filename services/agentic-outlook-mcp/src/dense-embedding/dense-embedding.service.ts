import { LangfuseConfig } from '@langfuse/openai';
import { startObservation } from '@langfuse/tracing';
import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { serializeError } from 'serialize-error-cjs';
import { VoyageAIClient } from 'voyageai';
import { AppConfig, AppSettings } from '../app-settings';
import { normalizeError } from '../utils/normalize-error';

@Injectable()
export class DenseEmbeddingService {
  public readonly voyageClient: VoyageAIClient;

  public constructor(configService: ConfigService<AppConfig, true>) {
    this.voyageClient = new VoyageAIClient({
      apiKey: configService.get(AppSettings.VOYAGE_API_KEY),
    });
  }

  /**
   * Embed the input using the Voyage contextualized embed model.
   * @param input - The input to embed.
   * @param config - The configuration for the embedding.
   * @returns The embeddings as a triple-nested array where:
   *   - First level: Array of document groups (matches input structure)
   *   - Second level: Array of chunks within each document group
   *   - Third level: Array of numbers representing the embedding vector for each chunk
   */
  public async contextualizedEmbed(
    input: string[][],
    inputType: 'document' | 'query' = 'document',
    config?: LangfuseConfig,
  ): Promise<number[][][]> {
    const span = startObservation(
      config?.generationName ?? 'Voyage-contextualized-embed',
      {
        model: 'voyage-context-3',
        input,
        modelParameters: {
          input_type: inputType,
        },
      },
      {
        asType: 'embedding',
        parentSpanContext: config?.parentSpanContext,
      },
    ).updateTrace({
      userId: config?.userId,
      sessionId: config?.sessionId,
      tags: config?.tags,
      name: config?.traceName,
    });

    try {
      const response = await this.voyageClient.contextualizedEmbed({
        model: 'voyage-context-3',
        inputs: input,
        inputType,
      });

      span
        .update({
          output: response.data,
          usageDetails: response.usage,
          model: response.model,
        })
        .end();

      return response.data?.map((data) => data.data?.map((d) => d.embedding ?? []) ?? []) ?? [];
    } catch (error) {
      span
        .update({
          statusMessage: String(error),
          level: 'ERROR',
          costDetails: {
            input: 0,
            output: 0,
            total: 0,
          },
        })
        .end();
      throw new Error('Failed to get contextualized embed', serializeError(normalizeError(error)));
    }
  }
}
