import { type Mocked, TestBed } from '@suites/unit';
import * as bcrypt from 'bcrypt';
import { beforeEach, describe, expect, it } from 'vitest';
import { IOAuthStore } from '../interfaces/io-auth-store.interface';
import { OAUTH_STORE_TOKEN } from '../mcp-oauth.module-definition';
import { ClientService } from './client.service';

describe('ClientService', () => {
  let clientService: ClientService;
  let store: Mocked<IOAuthStore>;

  beforeEach(async () => {
    const { unit, unitRef } = await TestBed.solitary(ClientService).compile();

    clientService = unit;
    store = unitRef.get(OAUTH_STORE_TOKEN);
  });

  describe('registerClient', () => {
    const registerClientDto = {
      client_name: 'test',
      redirect_uris: ['http://localhost:3000/mcp'],
      grant_types: ['authorization_code', 'refresh_token'],
      response_types: ['code'],
      token_endpoint_auth_method: 'none',
    };

    it('registers a dynamic oauthclient', async () => {
      store.storeClient.mockImplementation((client) => Promise.resolve(client));
      const client = await clientService.registerClient(registerClientDto);
      expect(client).toBeDefined();
    });

    it('generates a client id', async () => {
      store.generateClientId.mockReturnValue('test');
      store.storeClient.mockImplementation((client) => Promise.resolve(client));
      const client = await clientService.registerClient(registerClientDto);
      expect(client.client_id).toBe('test');
    });

    it('stores the client', async () => {
      store.storeClient.mockImplementation((client) => Promise.resolve(client));
      await clientService.registerClient(registerClientDto);
      expect(store.storeClient).toHaveBeenCalled();
    });

    it('returns the client with the plaintext secret', async () => {
      store.storeClient.mockImplementation((client) => Promise.resolve(client));
      const client = await clientService.registerClient({
        ...registerClientDto,
        token_endpoint_auth_method: 'client_secret_basic',
      });
      expect(client.client_secret).toBeDefined();
    });

    it('returns RFC 7591 compliant response with client_id_issued_at', async () => {
      store.generateClientId.mockReturnValue('test-client-id');
      store.storeClient.mockImplementation((client) => Promise.resolve(client));
      const client = await clientService.registerClient(registerClientDto);

      expect(client.client_id_issued_at).toBeDefined();
      expect(typeof client.client_id_issued_at).toBe('number');
      expect(client.client_id_issued_at).toBeGreaterThan(0);
    });

    it('returns client_secret_expires_at when client_secret is issued', async () => {
      store.storeClient.mockImplementation((client) => Promise.resolve(client));
      const client = await clientService.registerClient({
        ...registerClientDto,
        token_endpoint_auth_method: 'client_secret_basic',
      });

      expect(client.client_secret).toBeDefined();
      expect(client.client_secret_expires_at).toBe(0);
    });

    it('does not include client_secret_expires_at for public clients', async () => {
      store.storeClient.mockImplementation((client) => Promise.resolve(client));
      const client = await clientService.registerClient(registerClientDto);

      expect(client.client_secret).toBeUndefined();
      expect(client.client_secret_expires_at).toBeUndefined();
    });
  });

  describe('getClient', () => {
    it('returns the client when found', async () => {
      const mockClient = {
        client_id: 'test-id',
        client_name: 'test',
        redirect_uris: ['http://localhost:3000'],
        grant_types: ['authorization_code'],
        response_types: ['code'],
        token_endpoint_auth_method: 'none',
        created_at: new Date(),
        updated_at: new Date(),
      };
      store.getClient.mockResolvedValue(mockClient);

      const result = await clientService.getClient('test-id');

      expect(result).toEqual(mockClient);
      expect(store.getClient).toHaveBeenCalledWith('test-id');
    });

    it('returns null when client is not found', async () => {
      store.getClient.mockResolvedValue(undefined);
      const result = await clientService.getClient('non-existent');

      expect(result).toBeNull();
    });
  });

  describe('validateRedirectUri', () => {
    const mockClient = {
      client_id: 'test-id',
      client_name: 'test',
      redirect_uris: ['http://localhost:3000/callback', 'https://example.com/callback'],
      grant_types: ['authorization_code'],
      response_types: ['code'],
      token_endpoint_auth_method: 'none',
      created_at: new Date(),
      updated_at: new Date(),
    };

    it('returns true for exact redirect URI match', async () => {
      store.getClient.mockResolvedValue(mockClient);

      const result = await clientService.validateRedirectUri(
        'test-id',
        'https://example.com/callback',
      );

      expect(result).toBe(true);
    });

    it('returns true for localhost with different port', async () => {
      store.getClient.mockResolvedValue(mockClient);

      const result = await clientService.validateRedirectUri(
        'test-id',
        'http://localhost:8080/callback',
      );

      expect(result).toBe(true);
    });

    it('returns true for 127.0.0.1 with different port', async () => {
      const clientWith127 = {
        ...mockClient,
        redirect_uris: ['http://127.0.0.1:3000/callback'],
      };
      store.getClient.mockResolvedValue(clientWith127);

      const result = await clientService.validateRedirectUri(
        'test-id',
        'http://127.0.0.1:8080/callback',
      );

      expect(result).toBe(true);
    });

    it('returns false for non-matching redirect URI', async () => {
      store.getClient.mockResolvedValue(mockClient);

      const result = await clientService.validateRedirectUri(
        'test-id',
        'https://evil.com/callback',
      );

      expect(result).toBe(false);
    });

    it('returns false for invalid URL', async () => {
      store.getClient.mockResolvedValue(mockClient);

      const result = await clientService.validateRedirectUri('test-id', 'invalid-url');

      expect(result).toBe(false);
    });

    it('returns false when client is not found', async () => {
      store.getClient.mockResolvedValue(undefined);

      const result = await clientService.validateRedirectUri(
        'non-existent',
        'https://example.com/callback',
      );

      expect(result).toBe(false);
    });
  });

  describe('validateClientCredentials', async () => {
    const hashedSecret = await bcrypt.hash('correct-secret', 10);

    it('returns true for public client without secret', async () => {
      const publicClient = {
        client_id: 'public-client',
        client_name: 'test',
        redirect_uris: ['http://localhost:3000'],
        grant_types: ['authorization_code'],
        response_types: ['code'],
        token_endpoint_auth_method: 'none',
        client_secret: undefined,
        created_at: new Date(),
        updated_at: new Date(),
      };
      store.getClient.mockResolvedValue(publicClient);

      const result = await clientService.validateClientCredentials('public-client', undefined);

      expect(result).toBe(true);
    });

    it('returns false for public client with secret provided', async () => {
      const publicClient = {
        client_id: 'public-client',
        client_name: 'test',
        redirect_uris: ['http://localhost:3000'],
        grant_types: ['authorization_code'],
        response_types: ['code'],
        token_endpoint_auth_method: 'none',
        client_secret: undefined,
        created_at: new Date(),
        updated_at: new Date(),
      };
      store.getClient.mockResolvedValue(publicClient);

      const result = await clientService.validateClientCredentials('public-client', 'some-secret');

      expect(result).toBe(false);
    });

    it('returns true for confidential client with correct secret', async () => {
      const confidentialClient = {
        client_id: 'confidential-client',
        client_name: 'test',
        redirect_uris: ['http://localhost:3000'],
        grant_types: ['authorization_code'],
        response_types: ['code'],
        token_endpoint_auth_method: 'client_secret_basic',
        client_secret: hashedSecret,
        created_at: new Date(),
        updated_at: new Date(),
      };
      store.getClient.mockResolvedValue(confidentialClient);
      const result = await clientService.validateClientCredentials(
        'confidential-client',
        'correct-secret',
      );

      expect(result).toBe(true);
    });

    it('returns false for confidential client with incorrect secret', async () => {
      const confidentialClient = {
        client_id: 'confidential-client',
        client_name: 'test',
        redirect_uris: ['http://localhost:3000'],
        grant_types: ['authorization_code'],
        response_types: ['code'],
        token_endpoint_auth_method: 'client_secret_basic',
        client_secret: hashedSecret,
        created_at: new Date(),
        updated_at: new Date(),
      };
      store.getClient.mockResolvedValue(confidentialClient);
      const result = await clientService.validateClientCredentials(
        'confidential-client',
        'wrong-secret',
      );

      expect(result).toBe(false);
    });

    it('returns false for confidential client without secret', async () => {
      const confidentialClient = {
        client_id: 'confidential-client',
        client_name: 'test',
        redirect_uris: ['http://localhost:3000'],
        grant_types: ['authorization_code'],
        response_types: ['code'],
        token_endpoint_auth_method: 'client_secret_basic',
        client_secret: hashedSecret,
        created_at: new Date(),
        updated_at: new Date(),
      };
      store.getClient.mockResolvedValue(confidentialClient);

      const result = await clientService.validateClientCredentials(
        'confidential-client',
        undefined,
      );

      expect(result).toBe(false);
    });

    it('returns false when client is not found', async () => {
      store.getClient.mockResolvedValue(undefined);
      const result = await clientService.validateClientCredentials('non-existent', 'secret');

      expect(result).toBe(false);
    });
  });
});
