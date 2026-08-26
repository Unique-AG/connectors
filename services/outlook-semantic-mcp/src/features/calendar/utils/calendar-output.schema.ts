import * as z from 'zod';
import type { ResolvedWindow } from '~/utils/relative-range';

/**
 * Output fragments every calendar tool shares. They live here rather than being restated per tool
 * because the same field saying two different things is the drift the schema-harmony test now
 * fails on.
 */

export const ConsentRequiredSchema = z
  .boolean()
  .describe(
    'True when calendar scopes have not been granted yet. Ask the user to reconnect Outlook. Do not call reconnect_inbox.',
  );

/** Output counterpart of CalendarDateTime — one end of an event, slot, or schedule item. */
export const EventDateTimeSchema = z.object({
  dateTime: z
    .string()
    .describe('Local date and time of the boundary as returned by Graph, without a trailing Z.'),
  timeZone: z
    .string()
    .nullable()
    .describe('Windows or IANA timezone Graph attached to this boundary, or null if omitted.'),
});

export const ResolvedWindowSchema = z.object({
  startDateTime: z.string().describe('Absolute start sent to Graph, including timezone offset.'),
  endDateTime: z.string().describe('Absolute end sent to Graph, including timezone offset.'),
  timeZone: z
    .string()
    .describe(
      'IANA timezone the window was resolved in, or UTC when the mailbox timezone was unavailable.',
    ),
  serverCurrentDateTime: z
    .string()
    .describe('Server clock in that timezone when the window was resolved, including offset.'),
  interpretation: z
    .string()
    .describe(
      'Human description of the window, e.g. "next week = Mon 2026-08-31 00:00 to Sun 2026-09-06 23:59 (Europe/Zurich)". State this when a relative range was used.',
    ),
}) satisfies z.ZodType<ResolvedWindow>;
