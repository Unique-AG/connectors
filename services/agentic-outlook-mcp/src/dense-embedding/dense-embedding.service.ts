import { LangfuseConfig } from '@langfuse/openai';
import { startObservation } from '@langfuse/tracing';
import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import OpenAI from 'openai';
import { serializeError } from 'serialize-error-cjs';
import { VoyageAIClient } from 'voyageai';
import { AppConfig, AppSettings } from '../app-settings';
import { normalizeError } from '../utils/normalize-error';

const EMBEDDING_MODEL = 'qwen3-embedding-8b';
const BATCH_SIZE = 64;

@Injectable()
export class DenseEmbeddingService {
  public readonly voyageClient: VoyageAIClient | null = null;
  public readonly rawOpenAIClient: OpenAI;

  public constructor(configService: ConfigService<AppConfig, true>) {
    const voyageApiKey = configService.get(AppSettings.VOYAGE_API_KEY);
    if (voyageApiKey) {
      this.voyageClient = new VoyageAIClient({
        apiKey: voyageApiKey,
      });
    }
    this.rawOpenAIClient = new OpenAI({
      apiKey: configService.get(AppSettings.LITELLM_API_KEY),
      baseURL: configService.get(AppSettings.LITELLM_BASE_URL),
    });
  }

  public async embed(input: string[][], instruction?: string, config?: LangfuseConfig): Promise<number[][][]> {
    const span = startObservation(
      config?.generationName ?? 'Dense-embedding',
      {
        model: EMBEDDING_MODEL,
        input,
        metadata: {
          instruction,
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
      const flattenedInputs: string[] = [];
      const groupMetadata: { groupIndex: number; startIndex: number; count: number }[] = [];

      for (let groupIndex = 0; groupIndex < input.length; groupIndex++) {
        const group = input[groupIndex];
        if (!group) throw new Error(`Missing group or instruction at index ${groupIndex}`);

        const formattedInputs = instruction ? this.queryWithInstruction(group, instruction) : group;
        groupMetadata.push({
          groupIndex,
          startIndex: flattenedInputs.length,
          count: formattedInputs.length,
        });
        flattenedInputs.push(...formattedInputs);
      }

      const allEmbeddings: number[][] = [];
      let totalInputTokens = 0;

      for (let batchStart = 0; batchStart < flattenedInputs.length; batchStart += BATCH_SIZE) {
        const batchEnd = Math.min(batchStart + BATCH_SIZE, flattenedInputs.length);
        const batch = flattenedInputs.slice(batchStart, batchEnd);

        const response = await this.rawOpenAIClient.embeddings.create({
          model: EMBEDDING_MODEL,
          input: batch,
        });

        totalInputTokens += response.usage?.prompt_tokens ?? 0;

        for (const embeddingData of response.data) {
          allEmbeddings.push(embeddingData.embedding);
        }
      }

      const result: number[][][] = [];
      for (const metadata of groupMetadata) {
        const groupEmbeddings = allEmbeddings.slice(metadata.startIndex, metadata.startIndex + metadata.count);
        result.push(groupEmbeddings);
      }

      span
        .update({
          output: result,
          usageDetails: {
            input: totalInputTokens,
            total: totalInputTokens,
          },
        })
        .end();

      return result;
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
      throw new Error('Failed to get embeddings', serializeError(normalizeError(error)));
    }
  }

  private queryWithInstruction(input: string[], instruction: string): string[] {
    return input.map((query) => `Instruct: ${instruction}\nQuery: ${query}`);
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
    if (!this.voyageClient)
      throw new Error(
        'Voyage is not configured. Please set the VOYAGE_API_KEY environment variable to use Voyage.',
      );
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
