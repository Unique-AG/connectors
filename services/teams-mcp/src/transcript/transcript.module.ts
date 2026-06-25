import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/drizzle/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueModule } from '~/unique/unique.module';
import { PostAuthorizationListener } from './post-authorization.listener';
import { SubscriptionCreateService } from './subscription-create.service';
import { SubscriptionReauthorizeService } from './subscription-reauthorize.service';
import { SubscriptionRemoveService } from './subscription-remove.service';
import {
  FindTranscriptsTool,
  IngestMeetingTool,
  ListMeetingsTool,
  StartKbIntegrationTool,
  StopKbIntegrationTool,
  VerifyKbIntegrationStatusTool,
} from './tools';
import { TranscriptController } from './transcript.controller';
import { TranscriptCreatedService } from './transcript-created.service';
import { TranscriptRecordingService } from './transcript-recording.service';
import { TranscriptUtilsService } from './transcript-utils.service';

@Module({
  imports: [DrizzleModule, MsGraphModule, UniqueModule],
  providers: [
    TranscriptUtilsService,
    TranscriptRecordingService,
    SubscriptionCreateService,
    SubscriptionReauthorizeService,
    SubscriptionRemoveService,
    TranscriptCreatedService,
    // Auto-start ingestion at login (gated by MICROSOFT_AUTO_START_INGESTION)
    PostAuthorizationListener,
    // KB Integration MCP Tools
    VerifyKbIntegrationStatusTool,
    StartKbIntegrationTool,
    StopKbIntegrationTool,
    // Transcript Search Tools
    FindTranscriptsTool,
    ListMeetingsTool,
    // On-demand Ingestion Tool
    IngestMeetingTool,
  ],
  controllers: [TranscriptController],
})
export class TranscriptModule {}
