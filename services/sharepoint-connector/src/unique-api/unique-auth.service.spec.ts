import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Redacted } from '../utils/redacted';
import { UniqueAuthService } from './unique-auth.service';

vi.mock('undici', () => ({
  request: vi.fn(),
}));

const MOCK_UNIQUE_CONFIG = Object.freeze({
  serviceAuthMode: 'external' as const,
  zitadelOauthTokenUrl: 'https://auth.example.com/oauth/token',
  zitadelClientId: 'client',
  zitadelClientSecret: new Redacted('secret'),
  zitadelProjectId: 'proj-123',
  zitadelServiceExtraHeaders: {},
  ingestionMode: 'flat' as const,
  scopeId: 'scope-1',
  ingestionGraphqlUrl: 'https://ingestion.example.com/graphql',
  scopeManagementGraphqlUrl: 'https://scope.example.com/graphql',
  fileDiffUrl: 'https://diff.example.com/api',
  apiRateLimitPerMinute: 60,
});

describe('UniqueAuthService', () => {
  let service: UniqueAuthService;

  beforeEach(async () => {
    const { request } = await import('undici');
    vi.mocked(request).mockResolvedValue({
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
    } as never);

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
      .compile();
    service = unit;
  });

  it('gets a token from Zitadel', async () => {
    const { request } = await import('undici');
    const token = await service.getToken();
    expect(token).toBe('jwt-token');
    expect(request).toHaveBeenCalledWith(
      'https://auth.example.com/oauth/token',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          'Content-Type': 'application/x-www-form-urlencoded',
        }),
      }),
    );
  });

  it('includes extra headers in Zitadel request', async () => {
    const { request } = await import('undici');
    vi.mocked(request).mockResolvedValue({
      statusCode: 200,
      body: {
        text: vi.fn().mockResolvedValue(''),
        json: vi.fn().mockResolvedValue({
          access_token: 'jwt-token-with-headers',
          expires_in: 600,
          token_type: 'Bearer',
          id_token: 'id',
        }),
      },
    } as never);

    const configWithExtraHeaders = {
      ...MOCK_UNIQUE_CONFIG,
      zitadelServiceExtraHeaders: { 'x-zitadel-instance-host': 'id.example.com' },
    };

    const { unit } = await TestBed.solitary(UniqueAuthService)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'unique') {
            return configWithExtraHeaders;
          }
          return undefined;
        }),
      }))
      .compile();

    await unit.getToken();
    expect(request).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        headers: expect.objectContaining({
          'x-zitadel-instance-host': 'id.example.com',
        }),
      }),
    );
  });
});
