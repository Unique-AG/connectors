import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { N8nApiService } from './n8n-api.service';

@Module({
  imports: [ConfigModule],
  providers: [N8nApiService],
  exports: [N8nApiService],
})
export class N8nApiModule {}
