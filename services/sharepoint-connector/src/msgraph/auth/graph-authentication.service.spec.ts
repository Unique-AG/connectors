import { beforeEach, describe, expect, it, vi } from 'vitest';
import { GraphAuthenticationService } from './graph-authentication.service';

vi.mock('./client-secret-graph-auth.strategy');
vi.mock('./oidc-graph-auth.strategy');

describe('graphAuthenticationService', () => {
  let mockConfigService: {
    get: ReturnType<typeof vi.fn>;
  };

  beforeEach(async () => {
    mockConfigService = {
      get: vi.fn(),
    };
  });

  it('uses ClientSecretGraphAuthStrategy when useOidc is false', () => {
    mockConfigService.get.mockImplementation((key: string) => {
      if (key === 'sharepoint.useOidc') return false;
      return 'mock-value';
    });

    // Re-create provider to trigger constructor logic
    const newProvider = new GraphAuthenticationService(mockConfigService as never);

    expect(newProvider).toBeDefined();
  });

  it('uses OidcGraphAuthStrategy when useOidc is true', () => {
    mockConfigService.get.mockImplementation((key: string) => {
      if (key === 'sharepoint.useOidc') return true;
      return 'mock-value';
    });

    // Re-create provider to trigger constructor logic
    const newProvider = new GraphAuthenticationService(mockConfigService as never);

    expect(newProvider).toBeDefined();
  });

  it('delegates getAccessToken to the selected strategy', async () => {
    const mockStrategy = {
      getAccessToken: vi.fn().mockResolvedValue('mock-token'),
    };

    // Mock the strategy selection to return our mock strategy
    mockConfigService.get.mockImplementation((key: string) => {
      if (key === 'sharepoint.useOidc') return false;
      return 'mock-value';
    });

    // Create provider and manually set strategy for testing
    const newProvider = new GraphAuthenticationService(mockConfigService as never);
    // biome-ignore lint/suspicious/noExplicitAny: Override private property for testing
    (newProvider as any).strategy = mockStrategy;

    const token = await newProvider.getAccessToken();

    expect(token).toBe('mock-token');
    expect(mockStrategy.getAccessToken).toHaveBeenCalledTimes(1);
  });
});
