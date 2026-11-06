import assert from 'node:assert';
import { Redacted } from '@unique-ag/utils';
import pino from 'pino';
import { describe, expect, it } from 'vitest';
import type { AppConfig, KyckrConfig } from './config';
import { createAppLoggerOptions } from './logger-options';

const mockMcpApiKey = 'mcp-path-key-fixture';
const mockKyckrApiKey = 'kyckr-api-key-fixture';

const mockAppConfig = {
  logLevel: 'info',
  mcpApiKey: new Redacted(mockMcpApiKey),
} as AppConfig;
const mockKyckrConfig = { apiKey: new Redacted(mockKyckrApiKey) } as KyckrConfig;

function createCapturingLogger() {
  const { pinoHttp } = createAppLoggerOptions(mockAppConfig, mockKyckrConfig);
  assert.ok(
    typeof pinoHttp === 'object' && pinoHttp !== null && 'hooks' in pinoHttp,
    'Expected pinoHttp options with hooks',
  );
  const lines: string[] = [];
  const logger = pino({ hooks: pinoHttp.hooks }, { write: (line) => lines.push(line) });
  return { logger, lines };
}

describe('createAppLoggerOptions', () => {
  it('redacts the MCP api-key and the Kyckr API key from every line', () => {
    const { logger, lines } = createCapturingLogger();

    logger.error(
      { url: `/${mockMcpApiKey}/mcp` },
      `Kyckr rejected Bearer ${mockKyckrApiKey} on /${mockMcpApiKey}/mcp`,
    );

    expect(JSON.parse(lines[0] ?? '{}')).toMatchObject({
      url: '/[Redacted]/mcp',
      msg: 'Kyckr rejected Bearer [Redacted] on /[Redacted]/mcp',
    });
  });

  it('keeps the api-key out of the logged request url', () => {
    const { pinoHttp } = createAppLoggerOptions(mockAppConfig, mockKyckrConfig);
    assert.ok(
      typeof pinoHttp === 'object' && pinoHttp !== null && 'serializers' in pinoHttp,
      'Expected pinoHttp options with serializers',
    );

    expect(pinoHttp.serializers?.req?.({ url: `/${mockMcpApiKey}/mcp` })).toEqual({
      url: '/[Redacted]/mcp',
    });
  });
});
