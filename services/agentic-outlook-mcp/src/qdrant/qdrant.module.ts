import { Module } from "@nestjs/common";
import { QdrantService } from "./qdrant.service";

@Module({
  imports: [],
  providers: [QdrantService],
  exports: [QdrantService],
})
export class QdrantModule {}