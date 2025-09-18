import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { HttpClientModule } from '../http-client.module';
import { UniqueApiService } from './unique-api.service';

@Module({
  imports: [ConfigModule, HttpClientModule],
  providers: [UniqueApiService],
  exports: [UniqueApiService],
})
export class UniqueApiModule {}
