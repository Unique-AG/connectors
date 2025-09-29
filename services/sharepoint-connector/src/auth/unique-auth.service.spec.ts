import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UniqueAuthService } from './unique-auth.service';

// Mock fetch globally
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

describe('UniqueAuthService', () => {
  let service: UniqueAuthService;

  beforeEach(async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({
        access_token: 'jwt-token',
        expires_in: 600,
        token_type: 'Bearer',
        id_token: 'id',
      }),
    });

    const { unit } = await TestBed.solitary(UniqueAuthService)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'uniqueApi.zitadelOAuthTokenUrl')
            return 'https://auth.example.com/oauth/token';
          if (key === 'uniqueApi.zitadelClientId') return 'client';
          if (key === 'uniqueApi.zitadelClientSecret') return 'secret';
          if (key === 'uniqueApi.zitadelProjectId') return 'proj-123';
          return undefined;
        }),
      }))
      .compile();
    service = unit;
  });

  it('gets a token from Zitadel', async () => {
    const token = await service.getToken();
    expect(token).toBe('jwt-token');
    expect(mockFetch).toHaveBeenCalledWith(
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
