import { Temporal } from 'temporal-polyfill';
import * as z from 'zod';

const OFFSET_DATE_TIME = /(?:Z|[+-]\d{2}:\d{2})$/;

export function offsetDateTime(description: string) {
  return z
    .string()
    .regex(OFFSET_DATE_TIME, 'Must include a timezone offset such as +02:00 or Z')
    .refine((value) => {
      try {
        Temporal.Instant.from(value);
        return true;
      } catch {
        return false;
      }
    }, 'Must be a valid offset-bearing timestamp')
    .describe(description);
}
