import * as z from 'zod';
import { smtpAddress } from './smtp-address.schema';

export const EventRefSchema = z.object({
  eventId: z
    .string()
    .min(1)
    .describe('Internal Microsoft Graph event ID. Never display to the user.'),
  calendarId: z
    .string()
    .min(1)
    .describe('Internal Microsoft Graph calendar ID. Never display to the user.'),
  mailbox: smtpAddress(
    'SMTP address of the mailbox these IDs belong to. Never reconstruct eventRef; never display it.',
  ),
});
