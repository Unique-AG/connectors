import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/drizzle/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueModule } from '~/unique/unique.module';
import { OneNoteDeltaService } from './onenote-delta.service';
import { OneNoteGraphService } from './onenote-graph.service';
import { OneNotePermissionsService } from './onenote-permissions.service';
import { OneNoteSyncService } from './onenote-sync.service';
import { CreateOneNoteNotebookTool } from './tools/create-onenote-notebook.tool';
import { CreateOneNotePageTool } from './tools/create-onenote-page.tool';
import { SearchOneNoteTool } from './tools/search-onenote.tool';
import { StartOneNoteSyncTool } from './tools/start-onenote-sync.tool';
import { StopOneNoteSyncTool } from './tools/stop-onenote-sync.tool';
import { UpdateOneNotePageTool } from './tools/update-onenote-page.tool';
import { VerifyOneNoteSyncStatusTool } from './tools/verify-onenote-sync-status.tool';

@Module({
  imports: [DrizzleModule, MsGraphModule, UniqueModule],
  providers: [
    OneNoteGraphService,
    OneNoteDeltaService,
    OneNotePermissionsService,
    OneNoteSyncService,
    SearchOneNoteTool,
    CreateOneNotePageTool,
    UpdateOneNotePageTool,
    CreateOneNoteNotebookTool,
    StartOneNoteSyncTool,
    StopOneNoteSyncTool,
    VerifyOneNoteSyncStatusTool,
  ],
  exports: [OneNoteSyncService, OneNoteDeltaService],
})
export class OneNoteModule {}
