import { describe, expect, it } from 'vitest';
import { z } from 'zod';
import { ErrorCode, McpError } from '@modelcontextprotocol/sdk/types.js';
import { McpContent } from './mcp-content';
import { McpToolResult } from './mcp-tool-result';
import { ToolError, ResourceError, PromptError } from './tool-errors';
import { formatToolResult } from './format-tool-result';

describe('formatToolResult', () => {
  it('converts string return to text content', () => {
    const result = formatToolResult('hello');
    expect(result).toEqual({ content: [{ type: 'text', text: 'hello' }] });
  });

  it('converts number return to text content', () => {
    const result = formatToolResult(42);
    expect(result).toEqual({ content: [{ type: 'text', text: '42' }] });
  });

  it('converts boolean return to text content', () => {
    const result = formatToolResult(true);
    expect(result).toEqual({ content: [{ type: 'text', text: 'true' }] });
  });

  it('converts null to empty text content', () => {
    const result = formatToolResult(null);
    expect(result).toEqual({ content: [{ type: 'text', text: '' }] });
  });

  it('converts undefined to empty text content', () => {
    const result = formatToolResult(undefined);
    expect(result).toEqual({ content: [{ type: 'text', text: '' }] });
  });

  it('converts plain object (no schema) to JSON text', () => {
    const result = formatToolResult({ foo: 'bar', num: 1 });
    expect(result).toEqual({
      content: [{ type: 'text', text: JSON.stringify({ foo: 'bar', num: 1 }, null, 2) }],
    });
  });

  it('includes structuredContent when object matches outputSchema', () => {
    const schema = z.object({ name: z.string(), age: z.number() });
    const value = { name: 'Alice', age: 30 };
    const result = formatToolResult(value, schema);
    expect(result.structuredContent).toEqual(value);
    expect(result.content).toEqual([{ type: 'text', text: JSON.stringify(value, null, 2) }]);
  });

  it('throws McpError when object does not match outputSchema', () => {
    const schema = z.object({ name: z.string() });
    expect(() => formatToolResult({ name: 123 }, schema)).toThrow(McpError);
    expect(() => formatToolResult({ name: 123 }, schema)).toThrow(
      expect.objectContaining({ code: ErrorCode.InternalError }),
    );
  });

  it('passes through pre-formatted content array unchanged', () => {
    const preFormatted = { content: [{ type: 'text', text: 'already formatted' }], isError: false };
    const result = formatToolResult(preFormatted);
    expect(result).toBe(preFormatted);
  });

  it('passes through McpToolResult content and maps meta to _meta', () => {
    const toolResult = new McpToolResult({
      content: [{ type: 'text', text: 'from tool result' }],
      isError: false,
      meta: { requestId: 'abc123' },
    });
    const result = formatToolResult(toolResult);
    expect(result.content).toEqual([{ type: 'text', text: 'from tool result' }]);
    expect(result._meta).toEqual({ requestId: 'abc123' });
    expect(result.isError).toBe(false);
  });

  it('omits _meta when McpToolResult has no meta', () => {
    const toolResult = new McpToolResult({
      content: [{ type: 'text', text: 'no meta' }],
    });
    const result = formatToolResult(toolResult);
    expect('_meta' in result).toBe(false);
  });
});

describe('McpContent', () => {
  it('.text produces correct content structure', () => {
    const result = McpContent.text('hello');
    expect(result).toEqual({ content: [{ type: 'text', text: 'hello' }] });
  });

  it('.error produces content with isError true', () => {
    const result = McpContent.error('oops');
    expect(result.isError).toBe(true);
    expect(result.content).toEqual([{ type: 'text', text: 'oops' }]);
  });

  it('.image encodes buffer to base64 with correct mimeType', () => {
    const buffer = Buffer.from('fake-image-data');
    const result = McpContent.image(buffer, 'image/png');
    expect(result.content[0].type).toBe('image');
    expect(result.content[0].data).toBe(buffer.toString('base64'));
    expect(result.content[0].mimeType).toBe('image/png');
  });

  it('.audio uses default mimeType audio/mpeg', () => {
    const buffer = Buffer.from('fake-audio-data');
    const result = McpContent.audio(buffer);
    expect(result.content[0].type).toBe('audio');
    expect(result.content[0].mimeType).toBe('audio/mpeg');
    expect(result.content[0].data).toBe(buffer.toString('base64'));
  });

  it('.audio accepts custom mimeType', () => {
    const buffer = Buffer.from('fake-audio-data');
    const result = McpContent.audio(buffer, 'audio/wav');
    expect(result.content[0].mimeType).toBe('audio/wav');
  });
});

describe('ToolError', () => {
  it('has name "ToolError"', () => {
    const err = new ToolError('tool failed');
    expect(err.name).toBe('ToolError');
  });

  it('message is accessible', () => {
    const err = new ToolError('something broke');
    expect(err.message).toBe('something broke');
  });

  it('is an instance of Error', () => {
    expect(new ToolError('x')).toBeInstanceOf(Error);
  });
});

describe('ResourceError', () => {
  it('has name "ResourceError"', () => {
    const err = new ResourceError('resource not found');
    expect(err.name).toBe('ResourceError');
  });

  it('message is accessible', () => {
    const err = new ResourceError('resource unavailable');
    expect(err.message).toBe('resource unavailable');
  });

  it('is an instance of Error', () => {
    expect(new ResourceError('x')).toBeInstanceOf(Error);
  });
});

describe('PromptError', () => {
  it('has name "PromptError"', () => {
    const err = new PromptError('prompt failed');
    expect(err.name).toBe('PromptError');
  });

  it('message is accessible', () => {
    const err = new PromptError('invalid prompt');
    expect(err.message).toBe('invalid prompt');
  });

  it('is an instance of Error', () => {
    expect(new PromptError('x')).toBeInstanceOf(Error);
  });
});
