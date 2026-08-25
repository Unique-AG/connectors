import * as z from 'zod';
import { smtpAddress } from './smtp-address.schema';

export const CalendarRefSchema = z.object({
  calendarId: z
    .string()
    .min(1)
    .describe('Internal Microsoft Graph calendar ID. Never display to the user.'),
  mailbox: smtpAddress(
    'SMTP address of the mailbox this calendarId belongs to. This is not always the calendar owner: a calendar shared with the signed-in user is stored in their own mailbox. Never reconstruct calendarRef; never display it.',
  ),
});

export type CalendarRefInput = z.infer<typeof CalendarRefSchema>;
