import { Module } from '@nestjs/common';
import { DrizzleModule } from '../drizzle/drizzle.module';
import { MsGraphModule } from '../msgraph/msgraph.module';
import { FolderService } from './folder.service';

@Module({
  imports: [DrizzleModule, MsGraphModule],
  providers: [FolderService],
  exports: [FolderService],
})
export class FolderModule {}
