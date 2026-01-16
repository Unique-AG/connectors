import { type Mocked, TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it } from 'vitest';
import { RegisterClientDto } from '../dtos/register-client.dto';
import { ClientService } from '../services/client.service';
import { MetricService } from '../services/metric.service';
import { ClientController } from './client.controller';

describe('ClientController', () => {
  let controller: ClientController;
  let clientService: Mocked<ClientService>;
  let metricService: Mocked<MetricService>;

  beforeEach(async () => {
    const { unit, unitRef } = await TestBed.solitary(ClientController).compile();

    controller = unit;
    clientService = unitRef.get(ClientService);
    metricService = unitRef.get(MetricService);
  });

  describe('registerClient', () => {
    const mockRegisterDto: RegisterClientDto = {
      client_name: 'Test MCP Client',
      redirect_uris: ['http://localhost:3000/callback'],
      grant_types: ['authorization_code', 'refresh_token'],
      response_types: ['code'],
      token_endpoint_auth_method: 'none',
    };

    const mockRegisteredClient = {
      client_id: 'generated-client-id',
      client_name: 'Test MCP Client',
      redirect_uris: ['http://localhost:3000/callback'],
      grant_types: ['authorization_code', 'refresh_token'],
      response_types: ['code'],
      token_endpoint_auth_method: 'none',
      client_id_issued_at: Math.floor(Date.now() / 1000),
    };

    it('registers a new OAuth client successfully', async () => {
      clientService.registerClient.mockResolvedValue(mockRegisteredClient);

      const result = await controller.registerClient(mockRegisterDto);

      expect(clientService.registerClient).toHaveBeenCalledWith(mockRegisterDto);
      expect(metricService.incrementClientsRegistered).toHaveBeenCalled();
      expect(result).toEqual(mockRegisteredClient);
    });

    it('returns RFC 7591 compliant response with client_id_issued_at', async () => {
      clientService.registerClient.mockResolvedValue(mockRegisteredClient);

      const result = await controller.registerClient(mockRegisterDto);

      expect(result.client_id).toBe('generated-client-id');
      expect(result.client_id_issued_at).toBeDefined();
      expect(typeof result.client_id_issued_at).toBe('number');
    });

    it('returns client with secret and client_secret_expires_at for confidential clients', async () => {
      const confidentialDto: RegisterClientDto = {
        ...mockRegisterDto,
        token_endpoint_auth_method: 'client_secret_basic',
      };

      const mockConfidentialClient = {
        ...mockRegisteredClient,
        token_endpoint_auth_method: 'client_secret_basic',
        client_secret: 'generated-secret-123',
        client_secret_expires_at: 0,
      };

      clientService.registerClient.mockResolvedValue(mockConfidentialClient);

      const result = await controller.registerClient(confidentialDto);

      expect(result.client_secret).toBe('generated-secret-123');
      expect(result.client_secret_expires_at).toBe(0);
      expect(result.token_endpoint_auth_method).toBe('client_secret_basic');
    });

    it('handles service errors gracefully', async () => {
      const error = new Error('Database connection failed');
      clientService.registerClient.mockRejectedValue(error);

      await expect(controller.registerClient(mockRegisterDto)).rejects.toThrow(
        'Database connection failed',
      );

      expect(metricService.incrementClientsRegistered).toHaveBeenCalled();
    });

    it('accepts multiple redirect URIs', async () => {
      const multiRedirectDto: RegisterClientDto = {
        ...mockRegisterDto,
        redirect_uris: [
          'http://localhost:3000/callback',
          'http://localhost:3001/callback',
          'https://example.com/callback',
        ],
      };

      clientService.registerClient.mockResolvedValue({
        ...mockRegisteredClient,
        redirect_uris: multiRedirectDto.redirect_uris,
      });

      const result = await controller.registerClient(multiRedirectDto);

      expect(result.redirect_uris).toHaveLength(3);
      expect(clientService.registerClient).toHaveBeenCalledWith(multiRedirectDto);
    });
  });
});
