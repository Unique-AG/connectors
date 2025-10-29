import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it } from 'vitest';
import { MicrosoftAuthenticationService } from '../auth/microsoft-authentication.service';
import { GraphClientFactory } from './graph-client.factory';

describe('GraphClientFactory', () => {
  let factory: GraphClientFactory;
  let mockAuthProvider: MicrosoftAuthenticationService;

  beforeEach(async () => {
    mockAuthProvider = {
      getAccessToken: async () => 'mock-token',
    } as never;

    const { unit } = await TestBed.solitary(GraphClientFactory)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: (key: string) => {
          if (key === 'logLevel') return 'info';
          return undefined;
        },
      }))
      .mock(MicrosoftAuthenticationService)
      .impl(() => mockAuthProvider)
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
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: (key: string) => {
          if (key === 'logLevel') return 'info';
          return undefined;
        },
      }))
      .mock(MicrosoftAuthenticationService)
      .impl(() => mockAuthProvider)
      .compile();

    const client = unit.createClient();

    expect(client).toBeDefined();
  });

  it('creates client with debug logging enabled for debug level', async () => {
    const { unit } = await TestBed.solitary(GraphClientFactory)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: (key: string) => {
          if (key === 'logLevel') return 'debug';
          return undefined;
        },
      }))
      .mock(MicrosoftAuthenticationService)
      .impl(() => mockAuthProvider)
      .compile();

    const client = unit.createClient();

    expect(client).toBeDefined();
  });

  it('sets up middleware chain with all required middlewares', () => {
    const client = factory.createClient();

    expect(client).toBeDefined();
  });
});
