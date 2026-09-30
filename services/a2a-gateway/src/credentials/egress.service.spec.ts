import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { BadRequestException, ServiceUnavailableException } from '@nestjs/common';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { loadConfig } from '../config/config.js';
import { EgressBlockedError, EgressService } from './egress.service.js';

function rootCause(error: unknown): unknown {
  return error instanceof Error && error.cause ? rootCause(error.cause) : error;
}

function egress(environment: Record<string, string>) {
  return new EgressService(
    loadConfig({
      NODE_ENV: 'test',
      DATABASE_URL: 'postgresql://localhost/a2a',
      AMQP_URL: 'amqp://localhost',
      PUBLIC_BASE_URL: 'https://gateway.example/',
      ZITADEL_ISSUER: 'https://identity.example/',
      UNIQUE_CHAT_URL: 'http://node-chat/',
      UNIQUE_SCOPE_MANAGEMENT_URL: 'http://scope-management/',
      UNIQUE_INGESTION_URL: 'http://node-ingestion/',
      ENCRYPTION_KEY: '00'.repeat(32),
      ...environment,
    }),
  );
}

describe('EgressService', () => {
  let server: Server;
  let port: number;

  beforeAll(async () => {
    server = createServer((request, response) => {
      if (request.url === '/redirect') {
        response.writeHead(302, { location: 'http://169.254.169.254/' }).end();
        return;
      }
      response.writeHead(200, { 'content-type': 'text/plain' }).end('x'.repeat(100));
    });
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
    port = (server.address() as AddressInfo).port;
  });
  afterAll(() => new Promise<void>((resolve) => server.close(() => resolve())));

  it.each([
    'http://remote.example/card',
    'https://127.0.0.1/card',
    'https://[::1]/card',
    'https://169.254.169.254/latest',
  ])('rejects insecure or private destination %s by default', (url) => {
    const service = egress({
      EGRESS_ALLOWED_HOSTS: 'remote.example,127.0.0.1,[::1],169.254.169.254',
    });
    expect(() => service.approve(url)).toThrow(BadRequestException);
  });

  it('blocks an allowlisted name that resolves to a private address', async () => {
    const service = egress({ EGRESS_ALLOWED_HOSTS: 'localhost' });
    const error = await service.fetch(`https://localhost:${port}/`, {}).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ServiceUnavailableException);
    expect(rootCause(error)).toBeInstanceOf(EgressBlockedError);
  });

  it('never follows redirects', async () => {
    const service = egress({ EGRESS_ALLOWED_HOSTS: '127.0.0.1', EGRESS_ALLOW_INSECURE: 'true' });
    await expect(service.fetch(`http://127.0.0.1:${port}/redirect`, {})).rejects.toBeInstanceOf(
      ServiceUnavailableException,
    );
  });

  it('bounds streamed bodies', async () => {
    const service = egress({ EGRESS_ALLOWED_HOSTS: '127.0.0.1', EGRESS_ALLOW_INSECURE: 'true' });
    expect(await (await service.fetch(`http://127.0.0.1:${port}/`, {})).text()).toHaveLength(100);
    const response = await service.stream(`http://127.0.0.1:${port}/`, {}, 10);
    await expect(response.text()).rejects.toThrow();
  });

  it('refuses insecure egress in production', () => {
    expect(() => egress({ NODE_ENV: 'production', EGRESS_ALLOW_INSECURE: 'true' })).toThrow();
  });
});
