import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { AuthModule } from '../auth/auth.module';
import { HttpClientModule } from '../http-client.module';
import { SharepointApiService } from './sharepoint-api.service';

@Module({
  imports: [AuthModule, ConfigModule, HttpClientModule],
  providers: [SharepointApiService],
  exports: [SharepointApiService],
})
export class SharepointApiModule {}
