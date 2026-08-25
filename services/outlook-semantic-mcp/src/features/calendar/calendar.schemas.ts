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

export const EventRefSchema = z.object({
  eventId: z.string().describe('Internal Microsoft Graph event ID. Never display to the user.'),
  calendarId: z
    .string()
    .describe('Internal Microsoft Graph calendar ID. Never display to the user.'),
  accessPath: AccessPathSchema,
  mailbox: z
    .string()
    .describe(
      'SMTP address of the mailbox whose ID namespace this event belongs to. Pass eventRef verbatim to other calendar tools; never reconstruct it.',
    ),
});

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

const GraphDateTimeTimeZoneSchema = z.object({
  dateTime: z.string().optional(),
  timeZone: z.string().optional(),
});

const GraphAttendeeSchema = z.object({
  type: z.string().optional(),
  status: z.object({ response: z.string().optional() }).optional(),
  emailAddress: GraphEmailAddressSchema.optional(),
});

const GraphLocationSchema = z.object({
  displayName: z.string().optional(),
});

const GraphOnlineMeetingSchema = z.object({
  joinUrl: z.string().optional(),
});

const GraphBodySchema = z.object({
  content: z.string().optional(),
  contentType: z.string().optional(),
});

const GraphRecurrenceSchema = z.object({
  pattern: z
    .object({
      type: z.string().optional(),
      interval: z.number().optional(),
      daysOfWeek: z.array(z.string()).optional(),
    })
    .optional(),
});

const GraphEventSchema = z.object({
  id: z.string(),
  subject: z.string().optional().nullable(),
  body: GraphBodySchema.optional(),
  start: GraphDateTimeTimeZoneSchema.optional(),
  end: GraphDateTimeTimeZoneSchema.optional(),
  location: GraphLocationSchema.optional(),
  attendees: z.array(GraphAttendeeSchema).optional(),
  organizer: z.object({ emailAddress: GraphEmailAddressSchema.optional() }).optional(),
  isOnlineMeeting: z.boolean().optional(),
  onlineMeeting: GraphOnlineMeetingSchema.optional(),
  onlineMeetingUrl: z.string().optional().nullable(),
  webLink: z.string().optional().nullable(),
  isCancelled: z.boolean().optional(),
  isAllDay: z.boolean().optional(),
  sensitivity: z.string().optional(),
  categories: z.array(z.string()).optional(),
  type: z.string().optional(),
  seriesMasterId: z.string().optional().nullable(),
  recurrence: GraphRecurrenceSchema.optional().nullable(),
  showAs: z.string().optional(),
});

export const GraphEventCollectionSchema = z.object({
  value: z.array(GraphEventSchema).default([]),
  '@odata.nextLink': z.string().optional(),
});

export type GraphEvent = z.infer<typeof GraphEventSchema>;
