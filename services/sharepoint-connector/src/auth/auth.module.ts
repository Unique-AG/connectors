import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { UniqueAuthService } from './unique-auth.service';

@Module({
  imports: [ConfigModule],
  providers: [UniqueAuthService],
  exports: [UniqueAuthService],
})
export class AuthModule {}
