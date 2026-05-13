import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { BatchProcessorService } from './services/batch-processor.service';
import { HttpClientService } from './services/http-client.service';
import { MimeTypeResolverService } from './services/mime-type-resolver.service';

@Module({
  imports: [ConfigModule],
  providers: [BatchProcessorService, HttpClientService, MimeTypeResolverService],
  exports: [BatchProcessorService, HttpClientService, MimeTypeResolverService],
})
export class SharedModule {}
