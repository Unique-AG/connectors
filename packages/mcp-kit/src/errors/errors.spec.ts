import { describe, expect, it, vi } from 'vitest';
import { McpError, ErrorCode } from '@modelcontextprotocol/sdk/types.js';
import { DefectError, invariant } from './defect.js';
import { McpBaseError } from './base.js';
import {
  McpAuthenticationError,
  McpAuthorizationError,
  McpValidationError,
  McpToolError,
  McpProtocolError,
  UpstreamConnectionRequiredError,
  UpstreamConnectionLostError,
} from './failures.js';
import { handleMcpToolError, type McpLogger } from './mcp-exception-handler.js';

const noopLogger: McpLogger = { warn: () => undefined, error: () => undefined };

describe('invariant', () => {
  it('throws on falsy condition', () => {
    expect(() => invariant(false, 'expected true')).toThrow('expected true');
    expect(() => invariant(null, 'null is falsy')).toThrow('null is falsy');
    expect(() => invariant(0, 'zero is falsy')).toThrow('zero is falsy');
    expect(() => invariant('', 'empty string')).toThrow('empty string');
  });

  it('does not throw on truthy condition', () => {
    expect(() => invariant(true, 'msg')).not.toThrow();
    expect(() => invariant(1, 'msg')).not.toThrow();
    expect(() => invariant('value', 'msg')).not.toThrow();
    expect(() => invariant({}, 'msg')).not.toThrow();
  });

  // TypeScript narrows the type of `condition` to `true` after `invariant(condition, ...)`.
  // This is enforced at compile time via `asserts condition` — no runtime test needed.
});

describe('DefectError', () => {
  it('has _tag === "Defect"', () => {
    const err = new DefectError('programming mistake');
    expect(err._tag).toBe('Defect');
  });

  it('has name === "DefectError"', () => {
    const err = new DefectError('programming mistake');
    expect(err.name).toBe('DefectError');
  });

  it('is an instance of Error', () => {
    const err = new DefectError('oops');
    expect(err).toBeInstanceOf(Error);
  });
});

describe('McpBaseError subclasses', () => {
  const cases: Array<[string, McpBaseError, string]> = [
    ['McpAuthenticationError', new McpAuthenticationError('bad auth'), 'MCP_AUTHENTICATION_FAILED'],
    ['McpAuthorizationError', new McpAuthorizationError('forbidden'), 'MCP_AUTHORIZATION_FAILED'],
    ['McpValidationError', new McpValidationError('bad input'), 'MCP_VALIDATION_FAILED'],
    ['McpToolError', new McpToolError('tool failed'), 'MCP_TOOL_ERROR'],
    ['McpProtocolError', new McpProtocolError('protocol error'), 'MCP_PROTOCOL_ERROR'],
    [
      'UpstreamConnectionRequiredError',
      new UpstreamConnectionRequiredError('github', 'https://example.com/connect'),
      'MCP_UPSTREAM_CONNECTION_REQUIRED',
    ],
    [
      'UpstreamConnectionLostError',
      new UpstreamConnectionLostError('github'),
      'MCP_UPSTREAM_CONNECTION_LOST',
    ],
  ];

  for (const [className, instance, expectedErrorCode] of cases) {
    it(`${className} has errorCode "${expectedErrorCode}"`, () => {
      expect(instance.errorCode).toBe(expectedErrorCode);
    });

    it(`${className} has _tag === "McpFailure"`, () => {
      expect(instance._tag).toBe('McpFailure');
    });

    it(`${className} is an instance of McpBaseError`, () => {
      expect(instance).toBeInstanceOf(McpBaseError);
    });
  }

  it('McpAuthenticationError carries mcpErrorCode InvalidRequest', () => {
    const err = new McpAuthenticationError('auth failed');
    expect(err.metadata.mcpErrorCode).toBe(ErrorCode.InvalidRequest);
    expect(err.metadata.retryable).toBe(false);
  });

  it('McpAuthorizationError carries mcpErrorCode InvalidRequest', () => {
    const err = new McpAuthorizationError('forbidden');
    expect(err.metadata.mcpErrorCode).toBe(ErrorCode.InvalidRequest);
    expect(err.metadata.retryable).toBe(false);
  });

  it('McpValidationError carries mcpErrorCode InvalidParams', () => {
    const err = new McpValidationError('invalid');
    expect(err.metadata.mcpErrorCode).toBe(ErrorCode.InvalidParams);
    expect(err.metadata.retryable).toBe(false);
  });

  it('McpProtocolError uses caller-supplied mcpErrorCode', () => {
    const err = new McpProtocolError('protocol', ErrorCode.MethodNotFound);
    expect(err.metadata.mcpErrorCode).toBe(ErrorCode.MethodNotFound);
  });

  it('McpProtocolError allows undefined mcpErrorCode', () => {
    const err = new McpProtocolError('protocol');
    expect(err.metadata.mcpErrorCode).toBeUndefined();
  });
});

describe('UpstreamConnectionRequiredError', () => {
  it('stores upstreamName and reconnectUrl', () => {
    const err = new UpstreamConnectionRequiredError('github', 'https://example.com/connect');
    expect(err.upstreamName).toBe('github');
    expect(err.reconnectUrl).toBe('https://example.com/connect');
  });

  it('sets retryable to true', () => {
    const err = new UpstreamConnectionRequiredError('github', 'https://example.com/connect');
    expect(err.metadata.retryable).toBe(true);
  });

  it('formats message with upstream name', () => {
    const err = new UpstreamConnectionRequiredError('github', 'https://example.com/connect');
    expect(err.message).toBe('Upstream connection required: github');
  });
});

describe('UpstreamConnectionLostError', () => {
  it('stores upstreamName', () => {
    const err = new UpstreamConnectionLostError('slack');
    expect(err.upstreamName).toBe('slack');
  });

  it('uses default message when none provided', () => {
    const err = new UpstreamConnectionLostError('slack');
    expect(err.message).toBe('Upstream connection lost: slack');
  });

  it('uses provided message when given', () => {
    const err = new UpstreamConnectionLostError('slack', 'Connection dropped');
    expect(err.message).toBe('Connection dropped');
  });

  it('sets retryable to true', () => {
    const err = new UpstreamConnectionLostError('slack');
    expect(err.metadata.retryable).toBe(true);
  });
});

describe('handleMcpToolError', () => {
  it('rethrows McpError', () => {
    const mcpError = new McpError(ErrorCode.InvalidRequest, 'bad request');
    expect(() => handleMcpToolError(mcpError, noopLogger)).toThrow(mcpError);
  });

  it('rethrows UpstreamConnectionRequiredError', () => {
    const err = new UpstreamConnectionRequiredError('github', 'https://example.com/connect');
    expect(() => handleMcpToolError(err, noopLogger)).toThrow(err);
  });

  it('returns graceful error for McpBaseError', () => {
    const err = new McpAuthorizationError('not allowed');
    const result = handleMcpToolError(err, noopLogger);
    expect(result).toEqual({
      isError: true,
      content: [{ type: 'text', text: 'not allowed' }],
    });
  });

  it('returns graceful error for McpValidationError', () => {
    const err = new McpValidationError('field required');
    const result = handleMcpToolError(err, noopLogger);
    expect(result).toEqual({
      isError: true,
      content: [{ type: 'text', text: 'field required' }],
    });
  });

  it('returns internal error message for DefectError', () => {
    const err = new DefectError('invariant violated');
    const result = handleMcpToolError(err, noopLogger);
    expect(result).toEqual({
      isError: true,
      content: [{ type: 'text', text: 'Internal server error. This is a bug.' }],
    });
  });

  it('returns unexpected error message for unknown errors', () => {
    const result = handleMcpToolError(new Error('something went wrong'), noopLogger);
    expect(result).toEqual({
      isError: true,
      content: [{ type: 'text', text: 'An unexpected error occurred.' }],
    });
  });

  it('returns unexpected error message for non-Error unknowns', () => {
    const result = handleMcpToolError('a raw string error', noopLogger);
    expect(result).toEqual({
      isError: true,
      content: [{ type: 'text', text: 'An unexpected error occurred.' }],
    });
  });

  it('logs warn for McpBaseError', () => {
    const logger: McpLogger = { warn: vi.fn(), error: vi.fn() };
    const err = new McpAuthorizationError('denied');
    handleMcpToolError(err, logger);
    expect(logger.warn).toHaveBeenCalledWith(
      expect.stringContaining('MCP_AUTHORIZATION_FAILED'),
      undefined,
    );
  });

  it('logs error for DefectError', () => {
    const logger: McpLogger = { warn: vi.fn(), error: vi.fn() };
    const err = new DefectError('bug');
    handleMcpToolError(err, logger);
    const expectedStack = err.stack !== undefined ? err.stack : err.message;
    expect(logger.error).toHaveBeenCalledWith('[MCP] Defect encountered:', expectedStack);
  });

  it('logs error for unknown error', () => {
    const logger: McpLogger = { warn: vi.fn(), error: vi.fn() };
    const err = new Error('unknown');
    handleMcpToolError(err, logger);
    const expectedDetail = err.stack !== undefined ? err.stack : err.message;
    expect(logger.error).toHaveBeenCalledWith('[MCP] Unexpected error:', expectedDetail);
  });
});
