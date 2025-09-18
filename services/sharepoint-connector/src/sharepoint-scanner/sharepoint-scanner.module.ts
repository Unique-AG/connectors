import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { AuthModule } from '../auth/auth.module';
import { MsGraphModule } from '../msgraph/msgraph.module';
import { ProcessingPipelineModule } from '../processing-pipeline/processing-pipeline.module';
import { UniqueApiModule } from '../unique-api/unique-api.module';
import { SharepointScannerService } from './sharepoint-scanner.service';

@Module({
  imports: [ConfigModule, AuthModule, MsGraphModule, UniqueApiModule, ProcessingPipelineModule],
  providers: [SharepointScannerService],
  exports: [SharepointScannerService],
})
export class SharepointScannerModule {}
