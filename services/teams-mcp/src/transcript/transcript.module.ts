import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/drizzle/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueModule } from '~/unique/unique.module';
import { SubscriptionCreateService } from './subscription-create.service';
import { SubscriptionReauthorizeService } from './subscription-reauthorize.service';
import { SubscriptionRemoveService } from './subscription-remove.service';
import { TranscriptController } from './transcript.controller';
import { TranscriptCreatedService } from './transcript-created.service';
import { TranscriptUtilsService } from './transcript-utils.service';

@Module({
  imports: [DrizzleModule, MsGraphModule, UniqueModule],
  providers: [
    TranscriptUtilsService,
    SubscriptionCreateService,
    SubscriptionReauthorizeService,
    SubscriptionRemoveService,
    TranscriptCreatedService,
  ],
  controllers: [TranscriptController],
})
export class TranscriptModule {}
