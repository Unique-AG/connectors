import { Module } from '@nestjs/common';
import { SparseEmbeddingGrpcClient } from './sparse-embedding-grpc.client';

@Module({
  providers: [SparseEmbeddingGrpcClient],
  exports: [SparseEmbeddingGrpcClient],
})
export class SparseEmbeddingModule {}
