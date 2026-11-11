import type { Context } from '@unique-ag/mcp-server-module';
import { ErrorCode, McpError } from '@modelcontextprotocol/sdk/types.js';
import type { Logger } from '@nestjs/common';
import * as z from 'zod';

/** Accept / decline on the prompt is the confirmation. A boolean field would render as a checkbox on top of Confirm. */
export const ConfirmSchema = z.object({});

export type WriteConfirmation<T> =
  | { status: 'accepted'; content: T }
  | { status: 'declined' }
  | { status: 'unavailable'; message: string };

const TIMED_OUT =
  'The confirmation prompt timed out, so nothing was changed. Ask the user whether they still want this, then call the tool again.';
const UNSUPPORTED =
  'This client cannot show a confirmation prompt, and this change is not performed without one. Tell the user to run this from a client that supports confirmations.';
const INVALID_RESPONSE =
  'The confirmation response was invalid, so nothing was changed. Ask the user to try the confirmation again.';
const FAILED =
  'The confirmation prompt failed, so nothing was changed. Ask the user whether they still want this, then call the tool again.';

/**
 * Gates a write that cannot be undone: anything but an explicit accept, a failed prompt included,
 * means no write. There is no tool parameter to skip it, since injected email text could set one.
 */
export async function confirmWrite<T extends z.ZodRawShape>(input: {
  context: Context;
  schema: z.ZodObject<T>;
  message: string;
  logger: Logger;
  operation: string;
  userProfileId: string;
}): Promise<WriteConfirmation<z.infer<z.ZodObject<T>>>> {
  try {
    const result = await input.context.elicit(input.schema, input.message);
    if (result.action !== 'accept') {
      return { status: 'declined' };
    }
    return { status: 'accepted', content: result.content };
  } catch (error) {
    const message = elicitFailureMessage(error);
    input.logger.warn({
      userProfileId: input.userProfileId,
      operation: input.operation,
      msg: `${input.operation} confirmation unavailable`,
      err: error,
    });
    return { status: 'unavailable', message };
  }
}

function elicitFailureMessage(error: unknown): string {
  if (error instanceof McpError && error.code === ErrorCode.RequestTimeout) {
    return TIMED_OUT;
  }
  if (error instanceof McpError && error.code === ErrorCode.InvalidParams) {
    return INVALID_RESPONSE;
  }
  if (
    error instanceof Error &&
    /does not support (form |url )?elicitation|not supported in stateless/i.test(error.message)
  ) {
    return UNSUPPORTED;
  }
  return FAILED;
}
