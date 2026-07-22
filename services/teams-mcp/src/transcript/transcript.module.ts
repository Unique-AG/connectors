import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/drizzle/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueModule } from '~/unique/unique.module';
import { PostAuthorizationListener } from './post-authorization.listener';
import { SubscriptionCreateService } from './subscription-create.service';
import { SubscriptionReauthorizeService } from './subscription-reauthorize.service';
import { SubscriptionRemoveService } from './subscription-remove.service';
import {
  IngestMeetingTool,
  StartKbIntegrationTool,
  StopKbIntegrationTool,
  VerifyKbIntegrationStatusTool,
} from './tools';
import { TranscriptController } from './transcript.controller';
import { TranscriptCreatedService } from './transcript-created.service';
import { TranscriptRecordingService } from './transcript-recording.service';
import { TranscriptUtilsService } from './transcript-utils.service';

/**
 * Transcript ingestion + KB MCP tools. Only imported via KbIntegrationModule
 * when UNIQUE_INTEGRATION=enabled — do not import from AppModule directly.
 */
@Module({
  imports: [DrizzleModule, MsGraphModule, UniqueModule],
  providers: [
    TranscriptUtilsService,
    TranscriptRecordingService,
    SubscriptionCreateService,
    SubscriptionReauthorizeService,
    SubscriptionRemoveService,
    TranscriptCreatedService,
    // Auto-start ingestion at login (gated by UNIQUE_AUTO_START_INGESTION)
    PostAuthorizationListener,
    // KB Integration MCP Tools
    VerifyKbIntegrationStatusTool,
    StartKbIntegrationTool,
    StopKbIntegrationTool,
    // On-demand Ingestion Tool
    IngestMeetingTool,
  ],
  controllers: [TranscriptController],
})
export class TranscriptModule {}
