import * as z from 'zod';

export interface CalendarRef {
  calendarId: string;
  name: string;
  /**
   * The mailbox this calendar was listed from, and the only mailbox its calendarId resolves in.
   * Graph calendar and event ids are scoped to exactly one mailbox: an id read from
   * /users/{a}/calendars returns 404 under /users/{b}. This is provenance, not a property of the
   * calendar, so it can only ever be the path the id came from — never infer it from the owner or
   * from isDefaultCalendar/isTallyingResponses. A calendar somebody shared with you lives in
   * *your* mailbox even though ownerEmail is theirs.
   */
  mailbox: string;
  /** Display and filtering only. Who the calendar belongs to, which is not where its id resolves. */
  ownerEmail: string | null;
  ownerName: string | null;
  isOwn: boolean;
  canEdit: boolean;
  canViewPrivateItems: boolean;
}

export interface EventRef {
  eventId: string;
  calendarId: string;
  /** The mailbox both ids resolve in. See CalendarRef.mailbox. */
  mailbox: string;
}

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
  isTallyingResponses: z.boolean().optional(),
});

export const GraphCalendarCollectionSchema = z.object({
  value: z.array(GraphCalendarSchema).default([]),
  '@odata.nextLink': z.string().optional(),
});

export type GraphCalendar = z.infer<typeof GraphCalendarSchema>;

export const GraphDateTimeTimeZoneSchema = z.object({
  dateTime: z.string().optional(),
  timeZone: z.string().optional(),
});

export type GraphDateTimeTimeZone = z.infer<typeof GraphDateTimeTimeZoneSchema>;

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

const GraphScheduleItemSchema = z.object({
  isPrivate: z.boolean().optional(),
  status: z.string().optional(),
  subject: z.string().optional().nullable(),
  location: z.string().optional().nullable(),
  start: GraphDateTimeTimeZoneSchema.optional(),
  end: GraphDateTimeTimeZoneSchema.optional(),
});

const GraphWorkingHoursSchema = z.object({
  daysOfWeek: z.array(z.string()).optional(),
  startTime: z.string().optional(),
  endTime: z.string().optional(),
  timeZone: z.object({ name: z.string().optional() }).optional(),
});

const GraphScheduleInformationSchema = z.object({
  scheduleId: z.string().optional(),
  availabilityView: z.string().optional(),
  scheduleItems: z.array(GraphScheduleItemSchema).optional(),
  workingHours: GraphWorkingHoursSchema.nullish(),
  error: z
    .object({
      message: z.string().optional(),
      responseCode: z.string().optional(),
    })
    .nullish(),
});

export const GraphGetScheduleResponseSchema = z.object({
  value: z.array(GraphScheduleInformationSchema).default([]),
});

export type GraphScheduleInformation = z.infer<typeof GraphScheduleInformationSchema>;
export type GraphScheduleItem = z.infer<typeof GraphScheduleItemSchema>;

const GraphAttendeeAvailabilitySchema = z.object({
  availability: z.string().optional(),
  attendee: z
    .object({
      emailAddress: GraphEmailAddressSchema.optional(),
    })
    .optional(),
});

const GraphMeetingTimeSuggestionSchema = z.object({
  confidence: z.number().optional(),
  organizerAvailability: z.string().optional(),
  suggestionReason: z.string().optional(),
  attendeeAvailability: z.array(GraphAttendeeAvailabilitySchema).optional(),
  meetingTimeSlot: z
    .object({
      start: GraphDateTimeTimeZoneSchema.optional(),
      end: GraphDateTimeTimeZoneSchema.optional(),
    })
    .optional(),
});

export const GraphFindMeetingTimesResponseSchema = z.object({
  emptySuggestionsReason: z.string().optional(),
  meetingTimeSuggestions: z.array(GraphMeetingTimeSuggestionSchema).optional(),
});

export type GraphMeetingTimeSuggestion = z.infer<typeof GraphMeetingTimeSuggestionSchema>;

/**
 * Narrow projection a write tool reads before its confirmation prompt: enough to name the event
 * and decide occurrence vs. series, without pulling bodies or the full attendee list.
 */
export const GraphEventSnapshotSchema = z.object({
  id: z.string(),
  subject: z.string().nullish(),
  start: GraphDateTimeTimeZoneSchema.nullish(),
  end: GraphDateTimeTimeZoneSchema.nullish(),
  location: GraphLocationSchema.nullish(),
  attendees: z.array(z.unknown()).nullish(),
  organizer: z.object({ emailAddress: GraphEmailAddressSchema.nullish() }).nullish(),
  isCancelled: z.boolean().nullish(),
  type: z.string().nullish(),
  seriesMasterId: z.string().nullish(),
});

/** Shape Graph returns from POST /events and PATCH /events/{id}. */
export const GraphWrittenEventSchema = z.object({
  id: z.string(),
  subject: z.string().optional().nullable(),
  start: GraphDateTimeTimeZoneSchema.nullish(),
  end: GraphDateTimeTimeZoneSchema.nullish(),
  webLink: z.string().nullish(),
  onlineMeeting: GraphOnlineMeetingSchema.nullish(),
  onlineMeetingUrl: z.string().nullish(),
  location: GraphLocationSchema.nullish(),
});
