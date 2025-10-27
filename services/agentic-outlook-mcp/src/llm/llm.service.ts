import { LangfuseConfig, observeOpenAI } from '@langfuse/openai';
import { startObservation } from '@langfuse/tracing';
import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import OpenAI from 'openai';
import { ChatCompletionCreateParamsNonStreaming } from 'openai/resources/index';
import { serializeError } from 'serialize-error-cjs';
import { VoyageAIClient } from 'voyageai';
import { z } from 'zod';
import { AppConfig, AppSettings } from '../app-settings';
import { normalizeError } from '../utils/normalize-error';
import {
  parseCompletionOutput,
  parseInputArgs,
  parseModelDataFromResponse,
  parseUsageDetailsFromResponse,
} from './parse-openai.util';

export class LLMError extends Error {
  public constructor(
    message: string,
    public readonly cause?: unknown,
  ) {
    super(message);
  }
}

@Injectable()
export class LLMService {
  public readonly client: OpenAI;
  public readonly voyageClient: VoyageAIClient;

  public constructor(configService: ConfigService<AppConfig, true>) {
    const client = observeOpenAI(
      new OpenAI({
        apiKey: configService.get(AppSettings.LITELLM_API_KEY),
        baseURL: configService.get(AppSettings.LITELLM_BASE_URL),
      }),
    );
    this.client = client;
    this.voyageClient = new VoyageAIClient({
      apiKey: configService.get(AppSettings.VOYAGE_API_KEY),
    });
  }

  /**
   * Force the LLM to return a JSON object with the given schema and validate the output.
   * Supports Langfuse for tracing and metrics.
   * @param options - The options for the LLM call.
   * @param config - Additional optional Langfuse config.
   */
  public async generateObject<T extends z.ZodType>(
    options: ChatCompletionCreateParamsNonStreaming & {
      schema: T;
      schemaName?: string;
    },
    config?: LangfuseConfig,
  ): Promise<z.infer<T>> {
    const { schema, schemaName, ...rest } = options;

    const inputArgs = {
      ...rest,
      response_format: {
        type: 'json_schema' as const,
        json_schema: {
          name: schemaName ?? 'Output',
          schema: z.toJSONSchema(schema),
        },
      },
    };

    const { model, input, modelParameters } = parseInputArgs(inputArgs);
    const finalModelParams = { ...modelParameters, response_format: '' };
    const finalMetadata = {
      ...config?.generationMetadata,
      response_format:
        'response_format' in modelParameters ? modelParameters.response_format : undefined,
    };

    const generation = startObservation(
      config?.generationName ?? 'OpenAI-completion',
      {
        model,
        input,
        modelParameters: finalModelParams,
        prompt: config?.langfusePrompt,
        metadata: finalMetadata,
      },
      {
        asType: 'generation',
        parentSpanContext: config?.parentSpanContext,
      },
    ).updateTrace({
      userId: config?.userId,
      sessionId: config?.sessionId,
      tags: config?.tags,
      name: config?.traceName,
    });

    try {
      let output: unknown;
      // If the generation fails, set the cost to 0, as we don't have to pay for it.
      try {
        const response = await this.client.chat.completions.create(inputArgs);

        output = parseCompletionOutput(response);
        const usageDetails = parseUsageDetailsFromResponse(response);

        const {
          model: modelFromResponse,
          modelParameters: modelParametersFromResponse,
          metadata: metadataFromResponse,
        } = parseModelDataFromResponse(response);

        generation
          .update({
            output,
            // biome-ignore lint/suspicious/noExplicitAny: The langfuse sdk types are broken!
            usageDetails: usageDetails as any,
            model: modelFromResponse,
            modelParameters: modelParametersFromResponse,
            metadata: metadataFromResponse,
          })
          .end();
      } catch (error) {
        generation
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
        throw new LLMError(
          'Failed to get response from LLM',
          serializeError(normalizeError(error)),
        );
      }

      // If the parsing fails, throw an error, but don't null the costs, as we already paid for it.
      const content =
        typeof output === 'object' && output && 'content' in output ? output.content : output;
      if (typeof content !== 'string') throw new LLMError('Output content is not a string');
      const json = JSON.parse(content);
      return schema.parse(json);
    } catch (error) {
      generation
        .update({
          statusMessage: String(error),
          level: 'ERROR',
        })
        .end();
      throw new LLMError(
        'Failed to generate object with schema',
        serializeError(normalizeError(error)),
      );
    }
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
      throw new LLMError(
        'Failed to get contextualized embed',
        serializeError(normalizeError(error)),
      );
    }
  }
}
