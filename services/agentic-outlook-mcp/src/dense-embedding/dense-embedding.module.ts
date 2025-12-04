import { Module } from "@nestjs/common";
import { DenseEmbeddingService } from "./dense-embedding.service";

@Module({
  providers: [DenseEmbeddingService],
  exports: [DenseEmbeddingService],
})
export class DenseEmbeddingModule {}