import { Module } from '@nestjs/common';
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
export class TranscriptModule {}
