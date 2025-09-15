import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { AuthModule } from '../auth/auth.module';
import { SharepointApiService } from './sharepoint-api.service';

@Module({
  imports: [AuthModule, ConfigModule],
  providers: [SharepointApiService],
  exports: [SharepointApiService],
})
export class SharepointApiModule {}
