import { Module } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { Client } from 'undici';
import { Config } from './config';
import { SHAREPOINT_HTTP_CLIENT, UNIQUE_HTTP_CLIENT } from './http-client.tokens';

@Module({
  imports: [ConfigModule],
  providers: [
    {
      provide: UNIQUE_HTTP_CLIENT,
      useFactory: (configService: ConfigService<Config, true>) => {
        const fileDiffBaseUrl = configService.get('unique.fileDiffUrl', { infer: true });
        const url = new URL(fileDiffBaseUrl);
        return new Client(`${url.protocol}//${url.host}`, {
          bodyTimeout: 30000,
          headersTimeout: 5000,
        });
      },
      inject: [ConfigService],
    },
    {
      provide: SHAREPOINT_HTTP_CLIENT,
      useFactory: (configService: ConfigService<Config, true>) => {
        const apiUrl = configService.get('sharepoint.graphApiUrl', { infer: true });
        return new Client(apiUrl, {
          bodyTimeout: 30000,
          headersTimeout: 5000,
        });
      },
      inject: [ConfigService],
    },
  ],
  exports: [UNIQUE_HTTP_CLIENT, SHAREPOINT_HTTP_CLIENT],
})
export class HttpClientModule {}
