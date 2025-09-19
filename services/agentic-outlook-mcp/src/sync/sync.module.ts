import { Module } from '@nestjs/common';
import { DrizzleModule } from '../drizzle/drizzle.module';
import { MsGraphModule } from '../msgraph/msgraph.module';
import { FoldersController } from './folders/folders.controller';
import { FoldersService } from './folders/folders.service';
import { SyncController } from './sync.controller';
import { SyncService } from './sync.service';

@Module({
  controllers: [SyncController, FoldersController],
  imports: [DrizzleModule, MsGraphModule],
  providers: [SyncService, FoldersService],
  exports: [],
})
export class SyncModule {}
