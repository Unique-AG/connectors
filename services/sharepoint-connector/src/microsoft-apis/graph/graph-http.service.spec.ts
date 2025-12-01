import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  SPC_MS_GRAPH_API_REQUEST_DURATION_SECONDS,
  SPC_MS_GRAPH_API_SLOW_REQUESTS_TOTAL,
  SPC_MS_GRAPH_API_THROTTLE_EVENTS_TOTAL,
} from '../../metrics';
import { MicrosoftAuthenticationService } from '../auth/microsoft-authentication.service';
import { GraphHttpService } from './graph-http.service';

describe('GraphHttpService', () => {
  let service: GraphHttpService;
  let mockAuthService: {
    getAccessToken: ReturnType<typeof vi.fn>;
  };

  beforeEach(async () => {
    mockAuthService = {
      getAccessToken: vi.fn().mockResolvedValue('test-token'),
    };

    const mockHistogram = {
      record: vi.fn(),
    };

    const mockCounter = {
      add: vi.fn(),
    };

    const mockConfigService = {
      get: vi.fn().mockImplementation((key: string) => {
        if (key === 'sharepoint.authTenantId') {
          return 'test-tenant-id';
        }
        return undefined;
      }),
    };

    const { unit } = await TestBed.solitary(GraphHttpService)
      .mock(MicrosoftAuthenticationService)
      .impl(() => mockAuthService)
      .mock(SPC_MS_GRAPH_API_REQUEST_DURATION_SECONDS)
      .impl(() => mockHistogram)
      .mock(SPC_MS_GRAPH_API_THROTTLE_EVENTS_TOTAL)
      .impl(() => mockCounter)
      .mock(SPC_MS_GRAPH_API_SLOW_REQUESTS_TOTAL)
      .impl(() => mockCounter)
      .mock(ConfigService)
      .impl(() => mockConfigService)
      .compile();

    service = unit;
  });

  it('creates service successfully', () => {
    expect(service).toBeDefined();
  });

  it('has get method defined', () => {
    expect(service.get).toBeDefined();
    expect(typeof service.get).toBe('function');
  });

  it('has getStream method defined', () => {
    expect(service.getStream).toBeDefined();
    expect(typeof service.getStream).toBe('function');
  });

  it('has paginate method defined', () => {
    expect(service.paginate).toBeDefined();
    expect(typeof service.paginate).toBe('function');
  });
});
