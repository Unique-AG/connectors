import * as z from 'zod';

export const GraphDateTimeSchema = z.object({
  dateTime: z
    .string()
    .describe('Local date and time of the boundary as returned by Graph, without a trailing Z.'),
  timeZone: z
    .string()
    .nullable()
    .describe('Windows or IANA timezone Graph attached to this boundary, or null if omitted.'),
});

/** Collapses whitespace so a pasted multi-line subject cannot reflow an elicitation prompt. */
export function oneLine(value: string): string {
  return value.replaceAll(/\s+/g, ' ').trim();
}
