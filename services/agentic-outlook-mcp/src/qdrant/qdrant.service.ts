import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { QdrantClient } from '@qdrant/js-client-rest';
import { components } from '@qdrant/js-client-rest/dist/types/openapi/generated_schema';
import { Span } from 'nestjs-otel';
import { serializeError } from 'serialize-error-cjs';
import { AppConfig, AppSettings } from '../app-settings';
import { normalizeError } from '../utils/normalize-error';

@Injectable()
export class QdrantService {
  private readonly logger = new Logger(this.constructor.name);
  public readonly client: QdrantClient;

  public constructor(configService: ConfigService<AppConfig, true>) {
    this.client = new QdrantClient({ url: configService.get(AppSettings.QDRANT_URL) });
  }

  @Span('qdrant.ensureCollection')
  public async ensureCollection({
    name,
    vectors,
    sparseVectors,
  }: {
    name: string;
    vectors: Record<string, components['schemas']['VectorParams']>;
    sparseVectors?: Record<string, components['schemas']['SparseVectorParams']>;
  }) {
    try {
      const collection = await this.client.getCollection(name);

      if (collection.status !== 'green' && collection.status !== 'yellow') {
        throw new Error(`Collection ${name} is not ready`);
      }

      const existingVectors = collection.config.params.vectors;

      for (const [vectorName, vectorParams] of Object.entries(vectors)) {
        const existingVector = existingVectors?.[vectorName as keyof typeof existingVectors];

        if (!existingVector || typeof existingVector !== 'object') {
          throw new Error(`Collection ${name} is missing required vector: ${vectorName}`);
        }

        if (
          typeof existingVector === 'object' &&
          'size' in existingVector &&
          existingVector.size !== vectorParams.size
        ) {
          throw new Error(
            `Collection ${name} vector ${vectorName} has size ${existingVector.size}, expected ${vectorParams.size}`,
          );
        }

        if (
          typeof existingVector === 'object' &&
          'distance' in existingVector &&
          existingVector.distance !== vectorParams.distance
        ) {
          throw new Error(
            `Collection ${name} vector ${vectorName} has distance ${existingVector.distance}, expected ${vectorParams.distance}`,
          );
        }
      }

       const existingSparseVectors = collection.config.params.sparse_vectors;

       if (sparseVectors) {
       for (const [sparseVectorName, _] of Object.entries(sparseVectors)) {
        const existingSparseVector = existingSparseVectors?.[sparseVectorName as keyof typeof existingSparseVectors];

        if (!existingSparseVector || typeof existingSparseVector !== 'object') {
          throw new Error(`Collection ${name} is missing required sparse vector: ${sparseVectorName}`);
        }
      }}

      if (collection.status !== 'green' && collection.status !== 'yellow') {
        throw new Error(`Collection ${name} is not ready`);
      }

      return collection;
    } catch (error) {
      if (error instanceof Error && error.message.includes('Not Found')) {
        this.logger.log({
          msg: 'Collection not found, creating',
          name,
          vectors,
          error: serializeError(normalizeError(error)),
        });
      } else {
        throw error;
      }
    }

    // The speed of indexation may become a bottleneck in this case, as each user’s vector
    // will be indexed into the same collection. To avoid this bottleneck, consider bypassing
    // the construction of a global vector index for the entire collection and building it
    // only for individual groups instead.
    // By adopting this strategy, Qdrant will index vectors for each user independently,
    // significantly accelerating the process.
    await this.client.createCollection(name, {
      vectors,
      sparse_vectors: sparseVectors,
      // see: https://qdrant.tech/documentation/guides/multiple-partitions/#calibrate-performance
      hnsw_config: {
        payload_m: 16,
        m: 0,
      },
    });

    // Ensure Qdrant create a spearate index for each user's vectors
    await this.client.createPayloadIndex(name, {
      field_name: 'user_profile_id',
      field_schema: {
        type: 'keyword',
        is_tenant: true,
      },
    })

    const collection = await this.client.getCollection(name);

    return collection;
  }

  @Span('qdrant.upsert')
  public async upsert(
    collectionName: string,
    points: components['schemas']['PointStruct'][],
  ) {
    return this.client.upsert(collectionName, {
      points,
    });
  }

  @Span('qdrant.query')
  public async query(
    collectionName: string,
    request: components['schemas']['QueryRequest'],
  ) {
    return this.client.query(collectionName, request);
  }
}
