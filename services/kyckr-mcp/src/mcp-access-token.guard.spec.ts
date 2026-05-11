import type { ExecutionContext } from '@nestjs/common';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AppConfig } from '~/config';
import { McpAccessTokenGuard } from './mcp-access-token.guard';

const stubConfig = {
  mcpAccessToken: { value: 'test-mcp-access-token' },
} as AppConfig;

function makeExecutionContext(path: string, authorization?: string): ExecutionContext {
  return {
    switchToHttp: () => ({
      getRequest: () => ({
        path,
        headers: {
          authorization,
        },
      }),
    }),
  } as ExecutionContext;
}

describe('McpAccessTokenGuard', () => {
  let unit: McpAccessTokenGuard;

  beforeEach(() => {
    vi.clearAllMocks();
    unit = new McpAccessTokenGuard(stubConfig);
  });

  it('allows non-MCP routes without an Authorization header', () => {
    const context = makeExecutionContext('/probe');

    expect(unit.canActivate(context)).toBe(true);
  });

  it('rejects /mcp requests without an Authorization header', () => {
    const context = makeExecutionContext('/mcp');

    expect(unit.canActivate(context)).toBe(false);
  });

  it('rejects /mcp requests with a malformed Authorization header', () => {
    const context = makeExecutionContext('/mcp', 'Basic abc123');

    expect(unit.canActivate(context)).toBe(false);
  });

  it('rejects /mcp requests with an invalid bearer token', () => {
    const context = makeExecutionContext('/mcp', 'Bearer wrong-token');

    expect(unit.canActivate(context)).toBe(false);
  });

  it('allows /mcp requests with the expected bearer token', () => {
    const context = makeExecutionContext('/mcp', 'Bearer test-mcp-access-token');

    expect(unit.canActivate(context)).toBe(true);
  });

  it('protects nested /mcp routes as well', () => {
    const context = makeExecutionContext('/mcp/messages', 'Bearer test-mcp-access-token');

    expect(unit.canActivate(context)).toBe(true);
  });

  it('matches the MCP route case-insensitively', () => {
    const context = makeExecutionContext('/MCP/stream', 'Bearer test-mcp-access-token');

    expect(unit.canActivate(context)).toBe(true);
  });
});
