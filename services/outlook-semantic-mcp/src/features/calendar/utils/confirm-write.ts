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
  'The confirmation prompt timed out, so nothing was sent. Ask the user whether they still want this, then call the tool again.';
const UNSUPPORTED =
  'This client cannot show a confirmation prompt, and calendar writes are not performed without one. Tell the user to run this from a client that supports confirmations.';
const INVALID_RESPONSE =
  'The confirmation response was invalid, so nothing was sent. Ask the user to try the confirmation again.';
const FAILED =
  'The confirmation prompt failed, so nothing was sent. Ask the user whether they still want this, then call the tool again.';

/**
 * Runs the confirmation gate for a calendar write.
 *
 * Every outcome other than an explicit accept means no Graph write happens. That includes the
 * failure modes: a write tool here sends mail to third parties and cannot be undone, so a
 * confirmation we did not get is treated as a confirmation the user did not give. The failures are
 * turned into a typed result rather than propagating as a raw MCP error, so the model can relay
 * something useful and retry instead of surfacing a protocol error to the user.
 *
 * Deliberately not offered: a tool parameter that lets the model skip the prompt when elicitation
 * is unavailable. Tool descriptions are not a security boundary — these tools read meeting and
 * email text, which is attacker-controlled, so any bypass reachable by instruction is reachable by
 * injection. If a deployment needs unattended writes, that belongs in server config next to
 * CALENDAR_INTEGRATION, where an operator owns it and it can be audited.
 *
 * The schema should not include a confirmation boolean. Unique Chat already puts Accept / Decline
 * on the prompt; a boolean field is a second checkbox the user has to tick as well.
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
