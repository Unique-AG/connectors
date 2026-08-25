import { ErrorCode, McpError } from '@modelcontextprotocol/sdk/types.js';
import type { Logger } from '@nestjs/common';
import { describe, expect, it, vi } from 'vitest';
import * as z from 'zod';
import { confirmWrite } from '../confirm-write';

const SCHEMA = z.object({ confirmed: z.boolean() });

function run(elicit: ReturnType<typeof vi.fn>) {
  const warn = vi.fn();
  const result = confirmWrite({
    context: { elicit } as never,
    schema: SCHEMA,
    message: 'Confirm?',
    logger: { warn } as unknown as Logger,
    operation: 'create_event',
    userProfileId: 'user_profile_1',
  });
  return { result, warn };
}

describe(confirmWrite.name, () => {
  it('returns the content when the user accepts', async () => {
    const { result } = run(
      vi.fn().mockResolvedValue({ action: 'accept', content: { confirmed: true } }),
    );

    await expect(result).resolves.toEqual({ status: 'accepted', content: { confirmed: true } });
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

  it('explains when the client cannot show a prompt at all', async () => {
    const { result } = run(
      vi
        .fn()
        .mockRejectedValue(
          new Error('Client does not support elicitation (required for elicitation/create)'),
        ),
    );

    const outcome = await result;
    expect(outcome).toMatchObject({
      status: 'unavailable',
      message: expect.stringMatching(/cannot show a confirmation prompt/i),
    });
  });

  it('fails closed on an unexpected error instead of propagating it', async () => {
    const { result, warn } = run(vi.fn().mockRejectedValue(new Error('socket hang up')));

    await expect(result).resolves.toMatchObject({ status: 'unavailable' });
    expect(warn).toHaveBeenCalled();
  });
});
