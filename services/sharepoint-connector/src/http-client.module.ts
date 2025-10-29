import { Module } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { Client } from 'undici';
import { Config } from './config';
import { SHAREPOINT_REST_HTTP_CLIENT, UNIQUE_HTTP_CLIENT } from './http-client.tokens';

@Module({
  imports: [ConfigModule],
  providers: [
    {
      provide: UNIQUE_HTTP_CLIENT,
      useFactory: (configService: ConfigService<Config, true>) => {
        const fileDiffUrl = configService.get('unique.fileDiffUrl', { infer: true });
        const url = new URL(fileDiffUrl);
        return new Client(`${url.protocol}//${url.host}`, {
          bodyTimeout: 30000,
          headersTimeout: 30000,
        });
      },
      inject: [ConfigService],
    },
    {
      provide: SHAREPOINT_REST_HTTP_CLIENT,
      useFactory: (configService: ConfigService<Config, true>) => {
        const sharePointBaseUrl = configService.get('sharepoint.baseUrl', { infer: true });
        return new Client(sharePointBaseUrl, {
          bodyTimeout: 30000,
          headersTimeout: 30000,
        });
      },
      inject: [ConfigService],
    },
  ],
  exports: [UNIQUE_HTTP_CLIENT, SHAREPOINT_REST_HTTP_CLIENT],
})
export class HttpClientModule {}
