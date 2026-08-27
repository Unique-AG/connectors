import * as z from 'zod';
import { offsetDateTime } from './offset-date-time.schema';
import { RelativeRangeSchema } from './relative-range.schema';

export const DateRangeSchema = z
  .discriminatedUnion('rangeType', [
    z.object({
      rangeType: z
        .literal('relative')
        .describe(
          'Choose relative for a named server-resolved window, or absolute for explicit offset-bearing timestamps. Prefer relative. This branch is the named window.',
        ),
      range: RelativeRangeSchema.describe(
        'Named window such as today, thisWeek, or next7Days. Weeks start Monday.',
      ),
    }),
    z.object({
      rangeType: z
        .literal('absolute')
        .describe(
          'Choose relative for a named server-resolved window, or absolute for explicit offset-bearing timestamps. Prefer relative. This branch is the explicit window. Graph does not apply Prefer: outlook.timezone to these values.',
        ),
      startDateTime: offsetDateTime(
        'Inclusive start of the window, e.g. 2026-08-25T00:00:00+02:00. Offset is required; a naive timestamp is interpreted as UTC.',
      ),
      endDateTime: offsetDateTime(
        'End of the window, e.g. 2026-08-26T00:00:00+02:00. Offset is required.',
      ),
    }),
  ])
  .describe(
    "Choose 'relative' for a named server-resolved window or 'absolute' for explicit offset-bearing timestamps. Prefer relative.",
  );
