import * as z from 'zod';

export const CalendarRefSchema = z.object({
  calendarId: z
    .string()
    .min(1)
    .describe('Internal Microsoft Graph calendar ID. Never display to the user.'),
});

export type CalendarRefInput = z.infer<typeof CalendarRefSchema>;
