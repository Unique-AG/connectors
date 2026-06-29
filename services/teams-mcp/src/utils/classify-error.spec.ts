import { GraphError } from '@microsoft/microsoft-graph-client';
import { ErrorCode, McpError } from '@modelcontextprotocol/sdk/types.js';
import { describe, expect, it } from 'vitest';
import { classifyError, isUpstreamNetworkError, toAttributedError } from './classify-error';
import { MicrosoftReauthRequiredException } from './microsoft-reauth.exception';

function graphError(statusCode: number, code?: string, requestId?: string): GraphError {
  const error = new GraphError(statusCode, 'Error while processing response.');
  error.code = code ?? null;
  error.requestId = requestId ?? null;
  return error;
}

function networkError(code: string): Error {
  // Mirrors how undici surfaces transport failures: a `TypeError: fetch failed`
  // whose `.cause` carries the original errno.
  const error = new TypeError('fetch failed');
  (error as NodeJS.ErrnoException).cause = Object.assign(new Error(code), { code });
  return error;
}

describe('isUpstreamNetworkError', () => {
  it('is true for a "fetch failed" TypeError', () => {
    expect(isUpstreamNetworkError(new TypeError('fetch failed'))).toBe(true);
  });

  it('is true when error.cause.code is a transport code', () => {
    expect(isUpstreamNetworkError(networkError('EAI_AGAIN'))).toBe(true);
    expect(isUpstreamNetworkError(networkError('UND_ERR_CONNECT_TIMEOUT'))).toBe(true);
  });

  it('is true when the error itself carries a transport code', () => {
    expect(isUpstreamNetworkError(Object.assign(new Error('boom'), { code: 'ECONNRESET' }))).toBe(
      true,
    );
  });

  it('is false for unrelated errors', () => {
    expect(isUpstreamNetworkError(new Error('boom'))).toBe(false);
    expect(isUpstreamNetworkError(graphError(500))).toBe(false);
    expect(isUpstreamNetworkError(Object.assign(new Error('x'), { code: 'EACCES' }))).toBe(false);
  });
});

describe('classifyError', () => {
  it('classifies GraphError 500 as upstream_microsoft with attribution and requestId', () => {
    const result = classifyError(graphError(500, 'InternalServerError', 'req-123'));

    expect(result.fault).toBe('upstream_microsoft');
    expect(result.retryable).toBe(true);
    expect(result.httpStatus).toBe(500);
    expect(result.graphCode).toBe('InternalServerError');
    expect(result.requestId).toBe('req-123');
    expect(result.message).toContain("Microsoft's side");
    expect(result.message).toContain('500');
    expect(result.message).toContain('req-123');
  });

  it('classifies GraphError 503 as upstream_microsoft', () => {
    expect(classifyError(graphError(503, 'ServiceUnavailable')).fault).toBe('upstream_microsoft');
  });

  it('classifies GraphError 429 as upstream_microsoft', () => {
    const result = classifyError(graphError(429, 'TooManyRequests'));
    expect(result.fault).toBe('upstream_microsoft');
    expect(result.retryable).toBe(true);
  });

  it('classifies GraphError 401 as auth', () => {
    const result = classifyError(graphError(401, 'InvalidAuthenticationToken'));
    expect(result.fault).toBe('auth');
    expect(result.retryable).toBe(false);
  });

  it('classifies GraphError 400 as client_request with no Microsoft blame', () => {
    const result = classifyError(graphError(400, 'BadRequest'));
    expect(result.fault).toBe('client_request');
    expect(result.retryable).toBe(false);
    expect(result.message).not.toContain("Microsoft's side");
    expect(result.message).not.toContain('fault on');
  });

  it('classifies GraphError 404 as client_request', () => {
    expect(classifyError(graphError(404, 'NotFound')).fault).toBe('client_request');
  });

  it('classifies a fetch-failed network error as upstream_network', () => {
    const result = classifyError(networkError('EAI_AGAIN'));
    expect(result.fault).toBe('upstream_network');
    expect(result.retryable).toBe(true);
    expect(result.message).toContain('Microsoft Graph');
    expect(result.message).toContain('EAI_AGAIN');
  });

  it('classifies an arbitrary error as unknown, preserving the message', () => {
    const result = classifyError(new Error('something internal broke'));
    expect(result.fault).toBe('unknown');
    expect(result.message).toBe('something internal broke');
  });
});

describe('toAttributedError', () => {
  it('returns an McpError unchanged (preserves reauth flow)', () => {
    const reauth = new MicrosoftReauthRequiredException('invalid_grant');
    expect(toAttributedError(reauth)).toBe(reauth);

    const mcpError = new McpError(ErrorCode.InternalError, 'boom');
    expect(toAttributedError(mcpError)).toBe(mcpError);
  });

  it('returns the original error unchanged for unknown faults', () => {
    const original = new Error('non-upstream bug');
    expect(toAttributedError(original)).toBe(original);
  });

  it('rewrites a GraphError 500 into an attributed Error', () => {
    const result = toAttributedError(graphError(500, 'InternalServerError', 'req-xyz'));
    expect(result).toBeInstanceOf(Error);
    expect((result as Error).message).toContain("Microsoft's side");
    expect((result as Error).message).toContain('req-xyz');
  });

  it('rewrites a network error into an attributed Error', () => {
    const result = toAttributedError(networkError('EAI_AGAIN'));
    expect(result).toBeInstanceOf(Error);
    expect((result as Error).message).toContain('Could not reach Microsoft Graph');
  });
});
