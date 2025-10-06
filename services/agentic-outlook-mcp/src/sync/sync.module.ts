import { Module } from '@nestjs/common';
import { DrizzleModule } from '../drizzle/drizzle.module';
import { SyncController } from './sync.controller';
import { SyncService } from './sync.service';

@Module({
  imports: [DrizzleModule],
  controllers: [SyncController],
  providers: [SyncService],
  exports: [],
})
export class SyncModule {}
