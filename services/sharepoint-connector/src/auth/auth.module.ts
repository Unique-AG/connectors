import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { HttpClientModule } from '../http-client.module';
import { UniqueAuthService } from './unique-auth.service';

@Module({
  imports: [ConfigModule, HttpClientModule],
  providers: [UniqueAuthService],
  exports: [UniqueAuthService],
})
export class AuthModule {}
