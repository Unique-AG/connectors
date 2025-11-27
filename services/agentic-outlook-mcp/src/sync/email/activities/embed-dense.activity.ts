import { Activities, Activity } from '@unique-ag/temporal';
import { Injectable, Logger } from '@nestjs/common';
import { encodingForModel } from 'js-tiktoken';
import { PointInput } from '../../../drizzle';
import { LLMService } from '../../../llm/llm.service';

export interface IEmbedDenseActivity {
  embedDense(payload: EmbedDensePayload): Promise<PointInput[]>;
}

interface EmbedDensePayload {
  userProfileId: string;
  emailId: string;
  translatedSubject: string | null;
  translatedBody: string;
  summarizedBody: string;
  chunks: string[];
}

const MAX_TOKENS = 32_000;

@Injectable()
@Activities()
export class EmbedDenseActivity implements IEmbedDenseActivity {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly llmService: LLMService) {}

  @Activity()
  public async embedDense({
    userProfileId,
    emailId,
    translatedSubject,
    translatedBody,
    summarizedBody,
    chunks,
  }: EmbedDensePayload): Promise<PointInput[]> {
    const pointInputs = await this.createVectors(
      { id: emailId, userProfileId, translatedSubject, translatedBody, summarizedBody },
      chunks,
    );

    this.logger.debug({
      msg: 'Generated embeddings',
      vectorsCreated: pointInputs.length,
    });

    return pointInputs;
  }

  private countTokens(text: string): number {
    const enc = encodingForModel('gpt-4-turbo');
    const tokens = enc.encode(text);
    return tokens.length;
  }

  private async createVectors(
    email: {
      id: string;
      userProfileId: string;
      translatedSubject: string | null;
      translatedBody: string;
      summarizedBody: string;
    },
    chunks: string[],
  ): Promise<PointInput[]> {
    const pointInputs: PointInput[] = [];
    const documents = [];

    // We do not prefix or add the subject to the chunks as we have other vectors that will include the subject.
    // We're trying to not duplicate information in the vectors to avoid an overweight.
    // We will ingest multiple points per email, each with a different point type.
    // 1. Either the summarized body or the full email body with the subject
    // 2. If we chunked the email, we will ingest one point per chunk.
    if (email.summarizedBody) {
      documents.push([`Subject: ${email.translatedSubject}\n\nSummary: ${email.summarizedBody}`]);
      pointInputs.push({
        emailId: email.id,
        pointType: 'summary',
        vector: [],
        index: 0,
      });
    } else {
      const content = `Subject: ${email.translatedSubject}\n\nBody: ${email.translatedBody}`;
      if (this.countTokens(content) >= MAX_TOKENS - 50)
        throw new Error('Processed body is too long. Should have summarized');
      documents.push([content]);
      pointInputs.push({
        emailId: email.id,
        pointType: 'full',
        vector: [],
        index: 0,
      });
    }

    if (chunks.length > 1) {
      documents.push(chunks);
      for (let index = 0; index < chunks.length; index++) {
        pointInputs.push({
          emailId: email.id,
          pointType: 'chunk',
          vector: [],
          index,
        });
      }
    }

    if (documents.length === 0) {
      this.logger.warn({
        msg: 'Email has no documents to embed, skipping',
        emailId: email.id,
        userProfileId: email.userProfileId,
      });
      return [];
    }

    const embeddedDocuments = await this.llmService.contextualizedEmbed(documents);
    const fullOrSummaryVector = embeddedDocuments[0];
    if (!fullOrSummaryVector || !fullOrSummaryVector[0]) {
      throw new Error('Failed to get full or summary vector');
    }
    // biome-ignore lint/style/noNonNullAssertion: We know that pointInput exists.
    pointInputs[0]!.vector = fullOrSummaryVector[0];

    if (chunks.length > 1) {
      const chunkVectors = embeddedDocuments[1];
      if (chunkVectors) {
        for (let i = 0; i < chunkVectors.length; i++) {
          const vector = chunkVectors[i];
          if (!vector) continue;
          // Map to correct position in pointInputs: position 0 is summary/full, chunks start at position 1
          // biome-ignore lint/style/noNonNullAssertion: We know that pointInput exists.
          pointInputs[1 + i]!.vector = vector;
        }
      }
    }

    return pointInputs;
  }
}
