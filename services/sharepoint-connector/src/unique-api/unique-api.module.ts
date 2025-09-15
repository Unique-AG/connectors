import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { UniqueApiService } from './unique-api.service';

@Module({
  imports: [ConfigModule],
  providers: [UniqueApiService],
  exports: [UniqueApiService],
})
export class UniqueApiModule {}
