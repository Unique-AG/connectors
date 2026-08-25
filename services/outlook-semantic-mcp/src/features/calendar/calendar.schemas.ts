import * as z from 'zod';

export type CalendarAccessPath = 'ownMailbox' | 'ownerMailbox';

export interface CalendarRef {
  calendarId: string;
  name: string;
  ownerEmail: string | null;
  ownerName: string | null;
  isOwn: boolean;
  canEdit: boolean;
  canViewPrivateItems: boolean;
  accessPath: CalendarAccessPath;
}

export interface EventRef {
  eventId: string;
  calendarId: string;
  accessPath: CalendarAccessPath;
  mailbox: string;
}

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
  body: GraphBodySchema.nullish(),
  start: GraphDateTimeTimeZoneSchema.nullish(),
  end: GraphDateTimeTimeZoneSchema.nullish(),
  location: GraphLocationSchema.nullish(),
  attendees: z.array(GraphAttendeeSchema).nullish(),
  organizer: z.object({ emailAddress: GraphEmailAddressSchema.optional() }).nullish(),
  isOnlineMeeting: z.boolean().nullish(),
  onlineMeeting: GraphOnlineMeetingSchema.nullish(),
  onlineMeetingUrl: z.string().nullish(),
  webLink: z.string().nullish(),
  isCancelled: z.boolean().nullish(),
  isAllDay: z.boolean().nullish(),
  sensitivity: z.string().nullish(),
  categories: z.array(z.string()).nullish(),
  type: z.string().nullish(),
  seriesMasterId: z.string().nullish(),
  recurrence: GraphRecurrenceSchema.nullish(),
  showAs: z.string().nullish(),
});

export const GraphEventCollectionSchema = z.object({
  value: z.array(GraphEventSchema).default([]),
  '@odata.nextLink': z.string().optional(),
});

export type GraphEvent = z.infer<typeof GraphEventSchema>;
