import { type Context } from '@unique-ag/mcp-server-module';
import { ErrorCode, McpError } from '@modelcontextprotocol/sdk/types.js';
import type { Logger } from '@nestjs/common';
import { describe, expect, it, vi } from 'vitest';
import { ConfirmSchema, confirmWrite } from '../confirm-write';

const SCHEMA = ConfirmSchema;

function run(elicit: ReturnType<typeof vi.fn>) {
  const warn = vi.fn();
  const result = confirmWrite({
    context: { elicit } as unknown as Context,
    schema: SCHEMA,
    message: 'Confirm?',
    logger: { warn } as unknown as Logger,
    operation: 'create_event',
    userProfileId: 'user_profile_1',
  });
  return { result, warn };
}

describe(confirmWrite.name, () => {
  it('returns explicit content when the user accepts', async () => {
    const { result } = run(vi.fn().mockResolvedValue({ action: 'accept', content: {} }));

    await expect(result).resolves.toEqual({ status: 'accepted', content: {} });
  });

  it.each(['decline', 'cancel'])('reports %s as declined', async (action) => {
    const { result } = run(vi.fn().mockResolvedValue({ action, content: undefined }));

    await expect(result).resolves.toEqual({ status: 'declined' });
  });

  it('turns a timeout into an actionable unavailable result rather than throwing', async () => {
    const { result, warn } = run(
      vi.fn().mockRejectedValue(new McpError(ErrorCode.RequestTimeout, 'Request timed out')),
    );

    const outcome = await result;
    expect(outcome.status).toBe('unavailable');
    expect(outcome).toMatchObject({ message: expect.stringMatching(/timed out/i) });
    expect(outcome).toMatchObject({ message: expect.stringMatching(/nothing was sent/i) });
    expect(warn).toHaveBeenCalled();
  });

  it.each([
    'Client does not support elicitation.',
    'Client does not support form elicitation.',
    'Client does not support url elicitation.',
    'elicit is not supported in stateless mode',
  ])('explains when the client cannot show a prompt: %s', async (errorMessage) => {
    const { result } = run(vi.fn().mockRejectedValue(new Error(errorMessage)));

    const outcome = await result;
    expect(outcome).toMatchObject({
      status: 'unavailable',
      message: expect.stringMatching(/cannot show a confirmation prompt/i),
    });
  });

  it('reports malformed confirmation content as invalid rather than timed out', async () => {
    const { result } = run(
      vi.fn().mockRejectedValue(new McpError(ErrorCode.InvalidParams, 'applyTo is required')),
    );

    const outcome = await result;
    expect(outcome).toMatchObject({
      status: 'unavailable',
      message: expect.stringMatching(/invalid/i),
    });
    expect(outcome).toMatchObject({ message: expect.not.stringMatching(/timed out/i) });
  });

  it('fails closed on an unexpected error instead of propagating it', async () => {
    const { result, warn } = run(vi.fn().mockRejectedValue(new Error('socket hang up')));

    const outcome = await result;
    expect(outcome).toMatchObject({
      status: 'unavailable',
      message: expect.stringMatching(/failed/i),
    });
    expect(outcome).toMatchObject({ message: expect.not.stringMatching(/timed out/i) });
    expect(warn).toHaveBeenCalled();
  });
});
