import * as z from 'zod';

export const EventRefSchema = z.object({
  eventId: z
    .string()
    .min(1)
    .describe('Internal Microsoft Graph event ID. Never display to the user.'),
  calendarId: z
    .string()
    .min(1)
    .describe('Internal Microsoft Graph calendar ID. Never display to the user.'),
});
