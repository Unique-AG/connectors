import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { HttpClientModule } from '../http-client.module';
import { ScopeInitializerService } from './scope-initializer.service';
import { UniqueApiService } from './unique-api.service';
import { UniqueAuthService } from './unique-auth.service';

@Module({
  imports: [ConfigModule, HttpClientModule],
  providers: [UniqueApiService, UniqueAuthService, ScopeInitializerService],
  exports: [UniqueApiService, UniqueAuthService, ScopeInitializerService],
})
export class UniqueApiModule {}
