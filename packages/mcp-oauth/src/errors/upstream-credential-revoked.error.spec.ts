import { ErrorCode, McpError } from '@modelcontextprotocol/sdk/types.js';
import { describe, expect, it } from 'vitest';
import {
  isPermanentUpstreamOAuthError,
  isUpstreamCredentialRevokedError,
  UpstreamCredentialRevokedError,
} from './upstream-credential-revoked.error';

describe('UpstreamCredentialRevokedError', () => {
  it('treats Microsoft invalid_grant as a permanent upstream error', () => {
    expect(isPermanentUpstreamOAuthError('invalid_grant')).toBe(true);
    expect(isPermanentUpstreamOAuthError('temporarily_unavailable')).toBe(false);
    expect(isPermanentUpstreamOAuthError(undefined)).toBe(false);
  });

  it('identifies revoked-grant errors by name when instanceof would fail', () => {
    const aliased = { name: 'UpstreamCredentialRevokedError' };

    expect(
      isUpstreamCredentialRevokedError(new UpstreamCredentialRevokedError('invalid_grant')),
    ).toBe(true);
    expect(isUpstreamCredentialRevokedError(aliased)).toBe(true);
    expect(isUpstreamCredentialRevokedError(new Error('nope'))).toBe(false);
  });

  it('is an McpError so the MCP module emits a JSON-RPC error instead of a tool result', () => {
    const error = new UpstreamCredentialRevokedError('AADSTS50173');

    expect(error).toBeInstanceOf(McpError);
    expect(error.code).toBe(ErrorCode.InternalError);
    expect(error.name).toBe('UpstreamCredentialRevokedError');
  });

  it('carries the phrases clients match on both their thrown-error and tool-text paths', () => {
    const withCause = new UpstreamCredentialRevokedError('AADSTS50173').message.toLowerCase();
    const withoutCause = new UpstreamCredentialRevokedError().message.toLowerCase();

    for (const message of [withCause, withoutCause]) {
      expect(message).toContain('authentication required');
      expect(message).toContain('invalid token');
    }
    expect(withCause).toContain('AADSTS50173'.toLowerCase());
  });
});
