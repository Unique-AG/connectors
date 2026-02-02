import { join } from 'node:path';
import * as grpc from '@grpc/grpc-js';
import * as protoLoader from '@grpc/proto-loader';
import { Injectable, Logger, OnModuleInit } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { ProtoGrpcType } from '../@generated/grpc/sparse_embedding';
import { SparseEmbeddingServiceClient } from '../@generated/grpc/sparse_embedding/SparseEmbeddingService';
import { AppConfig, AppSettings } from '../app-settings';

@Injectable()
export class SparseEmbeddingGrpcClient implements OnModuleInit {
  private readonly logger = new Logger(SparseEmbeddingGrpcClient.name);
  private serverAddress: string;
  private client: SparseEmbeddingServiceClient | null = null;

  public constructor(private readonly configService: ConfigService<AppConfig, true>) {
    this.serverAddress = `${this.configService.get(AppSettings.SPARSE_EMBEDDING_GRPC_HOST)}:${this.configService.get(AppSettings.SPARSE_EMBEDDING_GRPC_PORT)}`;
  }

  public async onModuleInit() {
    const PROTO_PATH = join(__dirname, '../../proto/sparse_embedding.proto');

    const packageDefinition = protoLoader.loadSync(PROTO_PATH, {
      keepCase: true,
      longs: String,
      enums: String,
      defaults: true,
      oneofs: true,
    });

    const protoDescriptor = grpc.loadPackageDefinition(
      packageDefinition,
    ) as unknown as ProtoGrpcType;

    this.client = new protoDescriptor.sparse_embedding.SparseEmbeddingService(
      this.serverAddress,
      grpc.credentials.createInsecure(),
      {
        'grpc.keepalive_time_ms': 10000,
        'grpc.keepalive_timeout_ms': 5000,
        'grpc.keepalive_permit_without_calls': 1,
      },
    );

    this.logger.log(`gRPC client connected to ${this.serverAddress}`);
  }

  public async embedQuery(query: string): Promise<{ indices: number[]; values: number[] }> {
    return new Promise((resolve, reject) => {
      if (!this.client) return reject(new Error('gRPC client not initialized'));
      this.client.embedQuery({ query }, (error, response) => {
        if (error) {
          this.logger.error('Failed to generate sparse embedding', error);
          reject(error);
          return;
        }

        if (!response || !response.sparseVector) {
          reject(new Error('Invalid response from sparse embedding service'));
          return;
        }

        resolve({
          indices: response.sparseVector.indices,
          values: response.sparseVector.values,
        });
      });
    });
  }
}
