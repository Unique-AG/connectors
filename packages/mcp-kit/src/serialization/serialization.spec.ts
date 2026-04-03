import { describe, expect, it } from 'vitest';
import { z } from 'zod';
import { of, lastValueFrom } from 'rxjs';
import type { CallHandler, ExecutionContext } from '@nestjs/common';
import { McpContent } from './mcp-content';
import { McpToolResult } from './mcp-tool-result';
import { ToolError, ResourceError, PromptError } from './tool-errors';
import { McpZodValidationPipe } from '../pipes/mcp-zod-validation.pipe';
import { McpSerializationInterceptor } from '../interceptors/mcp-serialization.interceptor';
import { McpValidationError } from '../errors/failures';

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

  it('.file encodes buffer to base64 with uri and mimeType', () => {
    const buffer = Buffer.from('fake-data');
    const result = McpContent.file('data://doc', buffer, 'application/pdf');
    expect(result.content[0].type).toBe('resource');
    expect(result.content[0].resource.uri).toBe('data://doc');
    expect((result.content[0].resource as { blob: string }).blob).toBe(buffer.toString('base64'));
    expect(result.content[0].resource.mimeType).toBe('application/pdf');
  });

  it('.resourceLink produces correct resource_link content', () => {
    const result = McpContent.resourceLink('file://doc.pdf', 'My Doc', { title: 'My Title', mimeType: 'application/pdf' });
    expect(result.content[0].type).toBe('resource_link');
    expect(result.content[0].uri).toBe('file://doc.pdf');
    expect(result.content[0].name).toBe('My Doc');
    expect(result.content[0].title).toBe('My Title');
    expect(result.content[0].mimeType).toBe('application/pdf');
  });

  it('.resourceLink works with uri and name only', () => {
    const result = McpContent.resourceLink('https://example.com', 'Example');
    expect(result.content[0].type).toBe('resource_link');
    expect(result.content[0].uri).toBe('https://example.com');
    expect(result.content[0].name).toBe('Example');
    expect(result.content[0].title).toBeUndefined();
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

describe('McpZodValidationPipe', () => {
  it('passes valid input through', () => {
    const schema = z.object({ name: z.string() });
    const pipe = new McpZodValidationPipe(schema);
    expect(pipe.transform({ name: 'Alice' })).toEqual({ name: 'Alice' });
  });

  it('throws McpValidationError for invalid input', () => {
    const schema = z.object({ name: z.string() });
    const pipe = new McpZodValidationPipe(schema);
    expect(() => pipe.transform({ name: 123 })).toThrow(McpValidationError);
  });

  it('strips unknown fields (Zod default behavior)', () => {
    const schema = z.object({ name: z.string() });
    const pipe = new McpZodValidationPipe(schema);
    const result = pipe.transform({ name: 'Bob', extra: 'ignored' });
    expect(result).toEqual({ name: 'Bob' });
  });
});

describe('McpSerializationInterceptor', () => {
  const mockContext = {} as ExecutionContext;

  function makeCallHandler(value: unknown): CallHandler {
    return { handle: () => of(value) };
  }

  it('formats string return value', async () => {
    const interceptor = new McpSerializationInterceptor();
    const result = await lastValueFrom(interceptor.intercept(mockContext, makeCallHandler('hello')));
    expect(result).toEqual({ content: [{ type: 'text', text: 'hello' }] });
  });

  it('formats McpToolResult', async () => {
    const interceptor = new McpSerializationInterceptor();
    const toolResult = new McpToolResult({ content: [{ type: 'text', text: 'ok' }] });
    const result = await lastValueFrom(interceptor.intercept(mockContext, makeCallHandler(toolResult)));
    expect(result?.content).toEqual([{ type: 'text', text: 'ok' }]);
  });

  it('validates output against schema when provided', async () => {
    const schema = z.object({ name: z.string() });
    const interceptor = new McpSerializationInterceptor(schema);
    const result = await lastValueFrom(interceptor.intercept(mockContext, makeCallHandler({ name: 'Alice' })));
    expect(result?.structuredContent).toEqual({ name: 'Alice' });
  });
});
