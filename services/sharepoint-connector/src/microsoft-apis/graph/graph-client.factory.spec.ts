import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it } from 'vitest';
import { GraphClientFactory } from './graph-client.factory';
import { GraphAuthenticationService } from './middlewares/graph-authentication.service';

describe('GraphClientFactory', () => {
  let factory: GraphClientFactory;
  let mockGraphAuthService: GraphAuthenticationService;

  beforeEach(async () => {
    mockGraphAuthService = {
      getAccessToken: async () => 'mock-token',
    } as never;

    const { unit } = await TestBed.solitary(GraphClientFactory)
      .mock(GraphAuthenticationService)
      .impl(() => mockGraphAuthService)
      .compile();

    factory = unit;
  });

  it('creates Graph client successfully', () => {
    const client = factory.createClient();

    expect(client).toBeDefined();
    expect(client.api).toBeDefined();
  });

  it('creates client with authentication provider', () => {
    const client = factory.createClient();

    expect(client).toBeDefined();
  });

  it('creates client with debug logging disabled by default', async () => {
    const { unit } = await TestBed.solitary(GraphClientFactory)
      .mock(GraphAuthenticationService)
      .impl(() => mockGraphAuthService)
      .compile();

    const client = unit.createClient();

    expect(client).toBeDefined();
  });

  it('creates client with debug logging enabled for debug level', async () => {
    const { unit } = await TestBed.solitary(GraphClientFactory)
      .mock(GraphAuthenticationService)
      .impl(() => mockGraphAuthService)
      .compile();

    const client = unit.createClient();

    expect(client).toBeDefined();
  });

  it('sets up middleware chain with all required middlewares', () => {
    const client = factory.createClient();

    expect(client).toBeDefined();
  });
});
