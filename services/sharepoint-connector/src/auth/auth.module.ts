import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { SharepointAuthService } from './sharepoint-auth.service';
import { UniqueAuthService } from './unique-auth.service';

@Module({
  imports: [ConfigModule],
  providers: [SharepointAuthService, UniqueAuthService],
  exports: [SharepointAuthService, UniqueAuthService],
})
export class AuthModule {}
