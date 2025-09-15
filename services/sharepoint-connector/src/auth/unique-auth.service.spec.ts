import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { Client } from 'undici';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UNIQUE_HTTP_CLIENT } from '../http-client.tokens';
import { UniqueAuthService } from './unique-auth.service';

describe('UniqueAuthService', () => {
  let service: UniqueAuthService;
  let httpClient: Client;

  beforeEach(async () => {
    httpClient = {
      request: vi.fn().mockResolvedValue({
        body: {
          json: vi.fn().mockResolvedValue({
            access_token: 'jwt-token',
            expires_in: 600,
            token_type: 'Bearer',
            id_token: 'id',
          }),
        },
      }),
    } as unknown as Client;

    const { unit } = await TestBed.solitary(UniqueAuthService)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'uniqueApi.zitadelOAuthTokenUrl') return 'https://auth.example.com/oauth/token';
          if (key === 'uniqueApi.zitadelClientId') return 'client';
          if (key === 'uniqueApi.zitadelClientSecret') return 'secret';
          if (key === 'uniqueApi.zitadelProjectId') return 'proj-123';
          return undefined;
        }),
      }))
      .mock(UNIQUE_HTTP_CLIENT)
      .impl(() => httpClient)
      .compile();
    service = unit;
  });

  it('gets a token from Zitadel', async () => {
    const token = await service.getToken();
    expect(token).toBe('jwt-token');
  });
});
