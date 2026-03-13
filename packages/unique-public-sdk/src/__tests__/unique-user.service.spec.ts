import { TestBed } from '@suites/unit';
import { TraceService } from 'nestjs-otel';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UniqueUserService } from '../services/unique-user.service';
import { UNIQUE_PUBLIC_FETCH } from '../unique-public-sdk.consts';

const context = describe;

describe('UniqueUserService', () => {
  let service: UniqueUserService;
  let mockFetch: ReturnType<typeof vi.fn>;

  const validUser = {
    id: 'user-1',
    email: 'test@example.com',
    active: true,
    object: 'user' as const,
  };

  beforeEach(async () => {
    mockFetch = vi.fn();
    const { unit } = await TestBed.solitary(UniqueUserService)
      .mock(UNIQUE_PUBLIC_FETCH)
      .impl(() => mockFetch)
      .mock(TraceService)
      .impl(() => ({ getSpan: () => null }))
      .compile();
    service = unit;
  });

  describe('findUserByEmail', () => {
    context('when user is found by email', () => {
      it('returns the user result', async () => {
        mockFetch.mockImplementation((url: string) => {
          if (url.includes('email=')) {
            return Promise.resolve({
              ok: true,
              json: async () => ({ users: [validUser], object: 'users' }),
            });
          }
          return Promise.resolve({
            ok: true,
            json: async () => ({ users: [], object: 'users' }),
          });
        });

        const result = await service.findUserByEmail('test@example.com');

        expect(result).toEqual(validUser);
      });
    });

    context('when user is found by username but not email', () => {
      it('returns the user found by username', async () => {
        mockFetch.mockImplementation((url: string) => {
          if (url.includes('userName=')) {
            return Promise.resolve({
              ok: true,
              json: async () => ({ users: [validUser], object: 'users' }),
            });
          }
          return Promise.resolve({
            ok: true,
            json: async () => ({ users: [], object: 'users' }),
          });
        });

        const result = await service.findUserByEmail('test@example.com');

        expect(result).toEqual(validUser);
      });
    });

    context('when user is not found by either method', () => {
      it('returns null', async () => {
        mockFetch.mockResolvedValue({
          ok: true,
          json: async () => ({ users: [], object: 'users' }),
        });

        const result = await service.findUserByEmail('nonexistent@example.com');

        expect(result).toBeNull();
      });
    });

    context('when the API call fails', () => {
      it('returns null (error is swallowed)', async () => {
        mockFetch.mockRejectedValue(new Error('API error'));

        const result = await service.findUserByEmail('test@example.com');

        expect(result).toBeNull();
      });
    });

    context('when both email and username return the same user', () => {
      it('returns the email-matched user (email takes precedence)', async () => {
        const emailUser = { ...validUser, id: 'email-user' };
        const usernameUser = { ...validUser, id: 'username-user' };

        mockFetch.mockImplementation((url: string) => {
          if (url.includes('email=')) {
            return Promise.resolve({
              ok: true,
              json: async () => ({ users: [emailUser], object: 'users' }),
            });
          }
          return Promise.resolve({
            ok: true,
            json: async () => ({ users: [usernameUser], object: 'users' }),
          });
        });

        const result = await service.findUserByEmail('test@example.com');

        expect(result?.id).toBe('email-user');
      });
    });
  });
});
