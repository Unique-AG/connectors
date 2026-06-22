import assert from 'node:assert';
import { type Context } from '@unique-ag/mcp-server-module';
import { ConflictException, Logger } from '@nestjs/common';
import * as z from 'zod';

const logger = new Logger('disambiguate');

// Above this many matches a single-select picker is more hindrance than help;
// fall back to asking the user to be more specific instead.
const PICKER_MAX = 10;

/**
 * Resolve an ambiguous set of candidate entities to a single one by presenting
 * the user an interactive single-select picker via `context.elicit()`.
 *
 * Falls back to throwing the original `ConflictException` when the picker is
 * not an option: too many candidates, the user declines/cancels, or the client
 * (or stateless transport) does not support elicitation. This preserves today's
 * "be more specific" behaviour for non-elicitation clients.
 *
 * Callers handle the 0- and 1-match cases themselves; this is only invoked when
 * `matches.length > 1`.
 *
 * @param matches candidate entities (length > 1)
 * @param opts.toLabel human-readable label; MUST encode enough metadata
 *   (date/members/type) to tell duplicates apart
 * @param opts.promptMessage shown above the picker
 * @param opts.conflictMessage thrown when elicitation is unavailable/declined
 */
export async function disambiguate<T>(
  matches: T[],
  opts: {
    context: Context;
    toLabel: (item: T) => string;
    promptMessage: string;
    conflictMessage: string;
  },
): Promise<T> {
  if (matches.length > PICKER_MAX) {
    throw new ConflictException(opts.conflictMessage);
  }

  // Index-prefixed labels guarantee unique enum keys even if two items render
  // identically (e.g. two same-topic chats with no other distinguishing data).
  const labeled = matches.map((item, i) => ({ key: `${i + 1}. ${opts.toLabel(item)}`, item }));
  const keys = labeled.map((l) => l.key) as [string, ...string[]];

  try {
    const result = await opts.context.elicit(
      z.object({ selection: z.enum(keys).describe('Which one did you mean?') }),
      opts.promptMessage,
    );
    // User declined or cancelled the picker → let the caller retry with a better name.
    if (result.action !== 'accept') {
      throw new ConflictException(opts.conflictMessage);
    }
    const picked = labeled.find((l) => l.key === result.content.selection);
    // `selection` is constrained to `keys` by the enum and the framework
    // re-validates the response against the same schema, so this always matches.
    assert.ok(picked, 'elicited selection did not match any candidate');
    return picked.item;
  } catch (err) {
    // A decline/cancel surfaces as the ConflictException thrown above — rethrow it.
    if (err instanceof ConflictException) {
      throw err;
    }
    // Otherwise elicit itself threw — stateless mode or the client lacks the
    // elicitation capability. Log it so a genuinely unexpected error (rather
    // than the expected "elicitation unsupported") is still visible, then fall
    // back to today's behaviour.
    logger.warn(
      { err: err instanceof Error ? err.message : String(err) },
      'Elicitation failed; falling back to ConflictException',
    );
    throw new ConflictException(opts.conflictMessage);
  }
}
