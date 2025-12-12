import { DiscoveryModule } from '@golevelup/nestjs-discovery';
import { Module } from '@nestjs/common';
import { BatchController } from './batch.controller';
import { BatchService } from './batch.service';

@Module({
  imports: [DiscoveryModule],
  controllers: [BatchController],
  providers: [BatchService],
  exports: [],
})
export class BatchModule {}
