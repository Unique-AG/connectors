import * as z from 'zod';
import { smtpAddress } from './smtp-address.schema';

const AccessPathSchema = z
  .enum(['ownMailbox', 'ownerMailbox'])
  .describe('Internal Graph ID namespace. Never display this to the user.');

export const EventRefSchema = z.object({
  eventId: z
    .string()
    .min(1)
    .describe('Internal Microsoft Graph event ID. Never display to the user.'),
  calendarId: z
    .string()
    .min(1)
    .describe('Internal Microsoft Graph calendar ID. Never display to the user.'),
  accessPath: AccessPathSchema,
  mailbox: smtpAddress(
    'SMTP address of the mailbox whose ID namespace this event belongs to. Never reconstruct eventRef; never display it.',
  ),
});
