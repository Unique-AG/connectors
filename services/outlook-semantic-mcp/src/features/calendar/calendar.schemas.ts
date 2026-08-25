import * as z from 'zod';

export const AccessPathSchema = z
  .enum(['ownMailbox', 'ownerMailbox'])
  .describe(
    "Internal ID namespace. ownMailbox: event and calendar IDs belong to the caller and must be used with /me/calendars/{calendarId}. ownerMailbox: IDs belong to the owner's primary calendar and must be used with /users/{mailbox}/calendar. Never display this to the user.",
  );

export const CalendarRefSchema = z.object({
  calendarId: z
    .string()
    .describe(
      'Internal Microsoft Graph calendar ID. Pass to search_calendar_events as calendarIds. Never display to the user.',
    ),
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

export const EventRefSchema = z
  .object({
    eventId: z.string().describe('Internal Microsoft Graph event ID. Never display to the user.'),
    calendarId: z
      .string()
      .describe('Internal Microsoft Graph calendar ID. Never display to the user.'),
    accessPath: AccessPathSchema,
    mailbox: z
      .string()
      .nullable()
      .describe(
        'Owner SMTP address when accessPath is ownerMailbox; null when accessPath is ownMailbox. Never display to the user.',
      ),
  })
  .describe(
    'Internal handle for this event. Pass this object verbatim to respond_to_invite, update_event, or cancel_event without modification.',
  );

export type EventRef = z.infer<typeof EventRefSchema>;

export const GraphEmailAddressSchema = z.object({
  address: z.string().optional(),
  name: z.string().optional(),
});

export const GraphCalendarSchema = z.object({
  id: z.string(),
  name: z.string().optional(),
  owner: GraphEmailAddressSchema.optional(),
  canEdit: z.boolean().optional(),
  canShare: z.boolean().optional(),
  canViewPrivateItems: z.boolean().optional(),
  isDefaultCalendar: z.boolean().optional(),
});

export const GraphCalendarCollectionSchema = z.object({
  value: z.array(GraphCalendarSchema).default([]),
  '@odata.nextLink': z.string().optional(),
});

export const GraphDateTimeTimeZoneSchema = z.object({
  dateTime: z.string().optional(),
  timeZone: z.string().optional(),
});

export const GraphAttendeeSchema = z.object({
  type: z.string().optional(),
  status: z
    .object({
      response: z.string().optional(),
      time: z.string().optional(),
    })
    .optional(),
  emailAddress: GraphEmailAddressSchema.optional(),
});

export const GraphRecurrenceSchema = z
  .object({
    pattern: z
      .object({
        type: z.string().optional(),
        interval: z.number().optional(),
        daysOfWeek: z.array(z.string()).optional(),
        dayOfMonth: z.number().optional(),
        month: z.number().optional(),
        firstDayOfWeek: z.string().optional(),
        index: z.string().optional(),
      })
      .optional(),
    range: z
      .object({
        type: z.string().optional(),
        startDate: z.string().optional(),
        endDate: z.string().optional(),
        numberOfOccurrences: z.number().optional(),
      })
      .optional(),
  })
  .optional();

export const GraphEventSchema = z.object({
  id: z.string(),
  subject: z.string().nullable().optional(),
  body: z
    .object({
      contentType: z.string().optional(),
      content: z.string().optional(),
    })
    .optional(),
  start: GraphDateTimeTimeZoneSchema.optional(),
  end: GraphDateTimeTimeZoneSchema.optional(),
  location: z
    .object({
      displayName: z.string().optional(),
    })
    .optional(),
  attendees: z.array(GraphAttendeeSchema).optional(),
  organizer: z
    .object({
      emailAddress: GraphEmailAddressSchema.optional(),
    })
    .optional(),
  isOnlineMeeting: z.boolean().optional(),
  onlineMeetingUrl: z.string().nullable().optional(),
  onlineMeeting: z
    .object({
      joinUrl: z.string().nullable().optional(),
    })
    .optional(),
  webLink: z.string().optional(),
  isCancelled: z.boolean().optional(),
  sensitivity: z.string().optional(),
  categories: z.array(z.string()).optional(),
  type: z.string().optional(),
  seriesMasterId: z.string().nullable().optional(),
  recurrence: GraphRecurrenceSchema,
  responseStatus: z
    .object({
      response: z.string().optional(),
    })
    .optional(),
  showAs: z.string().optional(),
  isAllDay: z.boolean().optional(),
  isOrganizer: z.boolean().optional(),
});

export const GraphEventCollectionSchema = z.object({
  value: z.array(GraphEventSchema).default([]),
  '@odata.nextLink': z.string().optional(),
});

export type GraphCalendar = z.infer<typeof GraphCalendarSchema>;
export type GraphEvent = z.infer<typeof GraphEventSchema>;
