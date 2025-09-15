import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { AuthModule } from '../auth/auth.module';
import { ProcessingPipelineModule } from '../processing-pipeline/processing-pipeline.module';
import { SharepointApiModule } from '../sharepoint-api/sharepoint-api.module';
import { UniqueApiModule } from '../unique-api/unique-api.module';
import { SharepointScannerService } from './sharepoint-scanner.service';

@Module({
  imports: [
    ConfigModule,
    AuthModule,
    SharepointApiModule,
    UniqueApiModule,
    ProcessingPipelineModule,
  ],
  providers: [SharepointScannerService],
  exports: [SharepointScannerService],
})
export class SharepointScannerModule {}
