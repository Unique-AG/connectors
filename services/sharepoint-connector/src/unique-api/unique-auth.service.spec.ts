import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { HttpClientService } from '../shared/services/http-client.service';
import { Redacted } from '../utils/redacted';
import { UniqueAuthService } from './unique-auth.service';

const MOCK_UNIQUE_CONFIG = Object.freeze({
  serviceAuthMode: 'external' as const,
  zitadelOauthTokenUrl: 'https://auth.example.com/oauth/token',
  zitadelClientId: 'client',
  zitadelClientSecret: new Redacted('secret'),
  zitadelProjectId: 'proj-123',
  zitadelServiceExtraHeaders: {},
  ingestionMode: 'flat' as const,
  scopeId: 'scope-1',
  ingestionServiceBaseUrl: 'https://ingestion.example.com',
  scopeManagementServiceBaseUrl: 'https://scope.example.com',
  apiRateLimitPerMinute: 60,
});

describe('UniqueAuthService', () => {
  let service: UniqueAuthService;

  beforeEach(async () => {
    const mockHttpClientService = {
      request: vi.fn().mockResolvedValue({
        statusCode: 200,
        body: {
          text: vi.fn().mockResolvedValue(''),
          json: vi.fn().mockResolvedValue({
            access_token: 'jwt-token',
            expires_in: 600,
            token_type: 'Bearer',
            id_token: 'id',
          }),
        },
      }),
    };

    const { unit } = await TestBed.solitary(UniqueAuthService)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'unique') {
            return MOCK_UNIQUE_CONFIG;
          }
          return undefined;
        }),
      }))
      .mock(HttpClientService)
      .impl(() => mockHttpClientService)
      .compile();
    service = unit;
  });

  it('gets a token from Zitadel', async () => {
    const token = await service.getToken();
    expect(token).toBe('jwt-token');
    expect(service.httpClientService.request).toHaveBeenCalledWith(
      'https://auth.example.com/oauth/token',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          'Content-Type': 'application/x-www-form-urlencoded',
        }),
      }),
    );
  });
});
