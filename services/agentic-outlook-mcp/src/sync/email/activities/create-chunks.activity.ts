import { Activities, Activity } from '@unique-ag/temporal';
import { RecursiveCharacterTextSplitter } from '@langchain/textsplitters';
import { Injectable, Logger } from '@nestjs/common';

export interface ICreateChunksActivity {
  createChunks(payload: CreateChunksPayload): Promise<string[]>;
}

export interface CreateChunksPayload {
  body: string;
}

const CHUNK_SIZE = 3_200;
const CHUNK_OVERLAP = 400; // ~12.5% overlap, roughly 1-2 sentences

@Injectable()
@Activities()
export class CreateChunksActivity implements ICreateChunksActivity {
  private readonly logger = new Logger(this.constructor.name);

  @Activity()
  public async createChunks({ body }: CreateChunksPayload): Promise<string[]> {
    if (body.length < 5000) return [body];

    const splitter = new RecursiveCharacterTextSplitter({
      chunkSize: CHUNK_SIZE,
      chunkOverlap: CHUNK_OVERLAP,
    });

    const chunks = await splitter.splitText(body);

    this.logger.debug({
      msg: 'Created chunks',
      chunks: chunks.length,
    });

    return chunks;
  }
}
