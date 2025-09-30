import { Module } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { Client } from 'undici';
import { SHAREPOINT_HTTP_CLIENT, UNIQUE_HTTP_CLIENT } from './http-client.tokens';

@Module({
  imports: [ConfigModule],
  providers: [
    {
      provide: UNIQUE_HTTP_CLIENT,
      useFactory: (configService: ConfigService) => {
        const baseUrl = configService.get<string>('uniqueApi.ingestionUrl') as string;
        const url = new URL(baseUrl);
        return new Client(`${url.protocol}//${url.host}`, {
          bodyTimeout: 30000,
          headersTimeout: 5000,
        });
      },
      inject: [ConfigService],
    },
    {
      provide: SHAREPOINT_HTTP_CLIENT,
      useFactory: (configService: ConfigService) => {
        const apiUrl = configService.get<string>(
          'sharepoint.apiUrl',
          'https://graph.microsoft.com',
        );
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
