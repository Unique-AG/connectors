import { Module, type OnApplicationBootstrap } from '@nestjs/common';
import { TypeID } from 'typeid-js';
import { DrizzleModule } from '~/drizzle/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { TranscriptController } from './transcript.controller';
import { TranscriptService } from './transcript.service';

@Module({
  imports: [DrizzleModule, MsGraphModule],
  providers: [TranscriptService],
  controllers: [TranscriptController],
  exports: [TranscriptService],
})
export class TranscriptModule implements OnApplicationBootstrap {
  public constructor(
    private readonly svc: TranscriptService
  ) {}

  public async onApplicationBootstrap() {
    await this.svc.enqueueSubscriptionRequested(TypeID.fromString('user_profile_01k9q0hk8ce48sh82z27vfdxb5'));
  }
}
