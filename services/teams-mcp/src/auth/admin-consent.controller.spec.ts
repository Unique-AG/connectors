import {
  MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN,
  McpAuthJwtGuard,
  OpaqueTokenService,
} from '@unique-ag/mcp-oauth';
import { type INestApplication } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { APP_GUARD } from '@nestjs/core';
import { Test } from '@nestjs/testing';
import request from 'supertest';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AdminConsentController } from './admin-consent.controller';

const clientId = '7c4f0aab-b24e-48c4-9b2d-d1c22dfdf99f';
const redirectUri = 'https://www.example.com/setup/consent-completed/entra-id';
const foreignTenantId = 'f66cc3e7-9a7f-42ae-a0fa-adb72979b371';

describe('AdminConsentController', () => {
  let app: INestApplication | undefined;
  const validateAccessToken = vi.fn();

  const startApp = async (signInTenantId: string) => {
    const moduleRef = await Test.createTestingModule({
      controllers: [AdminConsentController],
      providers: [
        {
          provide: ConfigService,
          useValue: new ConfigService({
            microsoft: { clientId, signInTenantId, adminConsentRedirectUri: redirectUri },
          }),
        },
        { provide: APP_GUARD, useClass: McpAuthJwtGuard },
        { provide: OpaqueTokenService, useValue: { validateAccessToken } },
        {
          provide: MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN,
          useValue: { resource: 'https://teams.example.com/mcp' },
        },
      ],
    }).compile();

    app = moduleRef.createNestApplication();
    await app.init();
    return request(app.getHttpServer());
  };

  afterEach(async () => {
    await app?.close();
    app = undefined;
    validateAccessToken.mockReset();
  });

  it('redirects to the admin consent URL of a pinned tenant without an access token', async () => {
    const server = await startApp(foreignTenantId);

    const response = await server.get('/admin/consent');

    expect(response.status).toBe(302);
    expect(response.headers.location).toBe(
      `https://login.microsoftonline.com/${foreignTenantId}/v2.0/adminconsent` +
        `?client_id=${clientId}` +
        '&scope=https%3A%2F%2Fgraph.microsoft.com%2F.default' +
        '&redirect_uri=https%3A%2F%2Fwww.example.com%2Fsetup%2Fconsent-completed%2Fentra-id',
    );
    expect(validateAccessToken).not.toHaveBeenCalled();
  });

  it.each(['common', 'organizations', 'consumers', 'Common'])(
    'uses organizations when the server signs in to %s',
    async (signInTenantId) => {
      const server = await startApp(signInTenantId);

      const response = await server.get('/admin/consent');

      const location = new URL(response.headers.location ?? '');
      expect(location.pathname).toBe('/organizations/v2.0/adminconsent');
      expect(Object.fromEntries(location.searchParams)).toEqual({
        client_id: clientId,
        scope: 'https://graph.microsoft.com/.default',
        redirect_uri: redirectUri,
      });
    },
  );

  it('keeps a malformed tenant inside its path segment', async () => {
    const server = await startApp('evil/../x?y');

    const response = await server.get('/admin/consent');

    const location = new URL(response.headers.location ?? '');
    expect(location.host).toBe('login.microsoftonline.com');
    expect(location.pathname).toBe('/evil%2F..%2Fx%3Fy/v2.0/adminconsent');
  });
});
