import * as z from 'zod';

const AccessPathSchema = z
  .enum(['ownMailbox', 'ownerMailbox'])
  .describe('Internal Graph ID namespace. Never display this to the user.');

export const CalendarRefSchema = z.object({
  calendarId: z
    .string()
    .describe('Internal Microsoft Graph calendar ID. Never display to the user.'),
  name: z.string().describe('Display name of the calendar as shown in Outlook.'),
  ownerEmail: z
    .string()
    .nullable()
    .describe('SMTP address of the calendar owner, or null if Graph omitted it.'),
  ownerName: z
    .string()
    .nullable()
    .describe('Display name of the calendar owner, or null if Graph omitted it.'),
  isOwn: z
    .boolean()
    .describe(
      'True when this calendar belongs to the signed-in user, false when it is shared or delegated.',
    ),
  canEdit: z
    .boolean()
    .describe('True when the signed-in user can create or modify events on this calendar.'),
  canViewPrivateItems: z
    .boolean()
    .describe(
      'True when the signed-in user can see details of events marked private. When false, private events are returned redacted.',
    ),
  accessPath: AccessPathSchema,
});

export type CalendarRef = z.infer<typeof CalendarRefSchema>;

const GraphEmailAddressSchema = z.object({
  address: z.string().optional(),
  name: z.string().optional(),
});

const GraphCalendarSchema = z.object({
  id: z.string(),
  name: z.string().optional(),
  owner: GraphEmailAddressSchema.optional(),
  canEdit: z.boolean().optional(),
  canShare: z.boolean().optional(),
  canViewPrivateItems: z.boolean().optional(),
  isDefaultCalendar: z.boolean().optional(),
  isTallyingResponses: z.boolean().optional(),
});

export const GraphCalendarCollectionSchema = z.object({
  value: z.array(GraphCalendarSchema).default([]),
  '@odata.nextLink': z.string().optional(),
});

export type GraphCalendar = z.infer<typeof GraphCalendarSchema>;
