import { Schema } from "effect";

import { DateTimeTimeZoneSchema } from "./Common.js";

export const EventLocationSchema = Schema.Struct({
  displayName: Schema.String,
  locationType: Schema.optional(
    Schema.Literal(
      "default",
      "conferenceRoom",
      "homeAddress",
      "businessAddress",
      "geoCoordinates",
      "streetAddress",
      "hotel",
      "restaurant",
      "localBusiness",
      "postalAddress",
    ),
  ),
  uniqueId: Schema.optional(Schema.String),
  uniqueIdType: Schema.optional(Schema.String),
  address: Schema.optional(
    Schema.Struct({
      street: Schema.optional(Schema.String),
      city: Schema.optional(Schema.String),
      state: Schema.optional(Schema.String),
      countryOrRegion: Schema.optional(Schema.String),
      postalCode: Schema.optional(Schema.String),
    }),
  ),
  coordinates: Schema.optional(
    Schema.Struct({
      latitude: Schema.optional(Schema.Number),
      longitude: Schema.optional(Schema.Number),
    }),
  ),
});

export type EventLocation = Schema.Schema.Type<typeof EventLocationSchema>;

export const AttendeeSchema = Schema.Struct({
  emailAddress: Schema.Struct({
    address: Schema.String,
    name: Schema.optional(Schema.String),
  }),
  type: Schema.Literal("required", "optional", "resource"),
  status: Schema.optional(
    Schema.Struct({
      response: Schema.Literal("none", "organizer", "tentativelyAccepted", "accepted", "declined", "notResponded"),
      time: Schema.optional(Schema.String),
    }),
  ),
  proposedNewTime: Schema.optional(
    Schema.Struct({
      start: DateTimeTimeZoneSchema,
      end: DateTimeTimeZoneSchema,
    }),
  ),
});

export type Attendee = Schema.Schema.Type<typeof AttendeeSchema>;

export const PatternedRecurrenceSchema = Schema.Struct({
  pattern: Schema.optional(
    Schema.Struct({
      type: Schema.Literal("daily", "weekly", "absoluteMonthly", "relativeMonthly", "absoluteYearly", "relativeYearly"),
      interval: Schema.Number,
      month: Schema.optional(Schema.Number),
      dayOfMonth: Schema.optional(Schema.Number),
      daysOfWeek: Schema.optional(Schema.Array(Schema.String)),
      firstDayOfWeek: Schema.optional(Schema.String),
      index: Schema.optional(Schema.String),
    }),
  ),
  range: Schema.optional(
    Schema.Struct({
      type: Schema.Literal("endDate", "noEnd", "numbered"),
      startDate: Schema.String,
      endDate: Schema.optional(Schema.String),
      recurrenceTimeZone: Schema.optional(Schema.String),
      numberOfOccurrences: Schema.optional(Schema.Number),
    }),
  ),
});

export type PatternedRecurrence = Schema.Schema.Type<typeof PatternedRecurrenceSchema>;

export const CalendarEventSchema = Schema.Struct({
  id: Schema.String,
  subject: Schema.String,
  body: Schema.Struct({
    contentType: Schema.Literal("text", "html"),
    content: Schema.String,
  }),
  bodyPreview: Schema.optional(Schema.String),
  start: DateTimeTimeZoneSchema,
  end: DateTimeTimeZoneSchema,
  location: Schema.optional(EventLocationSchema),
  locations: Schema.optional(Schema.Array(EventLocationSchema)),
  attendees: Schema.Array(AttendeeSchema),
  organizer: Schema.optional(
    Schema.Struct({
      emailAddress: Schema.Struct({
        address: Schema.String,
        name: Schema.optional(Schema.String),
      }),
    }),
  ),
  isAllDay: Schema.Boolean,
  isCancelled: Schema.Boolean,
  isOnlineMeeting: Schema.Boolean,
  onlineMeetingUrl: Schema.NullOr(Schema.String),
  onlineMeeting: Schema.optional(
    Schema.NullOr(
      Schema.Struct({
        joinUrl: Schema.optional(Schema.String),
        conferenceId: Schema.optional(Schema.String),
        tollNumber: Schema.optional(Schema.String),
      }),
    ),
  ),
  recurrence: Schema.NullOr(PatternedRecurrenceSchema),
  importance: Schema.Literal("low", "normal", "high"),
  sensitivity: Schema.Literal("normal", "personal", "private", "confidential"),
  showAs: Schema.optional(
    Schema.Literal("free", "tentative", "busy", "oof", "workingElsewhere", "unknown"),
  ),
  responseStatus: Schema.optional(
    Schema.Struct({
      response: Schema.Literal("none", "organizer", "tentativelyAccepted", "accepted", "declined", "notResponded"),
      time: Schema.optional(Schema.String),
    }),
  ),
  createdDateTime: Schema.optional(Schema.String),
  lastModifiedDateTime: Schema.optional(Schema.String),
  changeKey: Schema.optional(Schema.String),
  categories: Schema.optional(Schema.Array(Schema.String)),
  seriesMasterId: Schema.optional(Schema.NullOr(Schema.String)),
  type: Schema.optional(
    Schema.Literal("singleInstance", "occurrence", "exception", "seriesMaster"),
  ),
  webLink: Schema.optional(Schema.String),
  onlineMeetingProvider: Schema.optional(
    Schema.Literal("unknown", "skypeForBusiness", "skypeForConsumer", "teamsForBusiness"),
  ),
  hasAttachments: Schema.optional(Schema.Boolean),
  reminderMinutesBeforeStart: Schema.optional(Schema.Number),
  isReminderOn: Schema.optional(Schema.Boolean),
  iCalUId: Schema.optional(Schema.String),
});

export type CalendarEvent = Schema.Schema.Type<typeof CalendarEventSchema>;

export const CreateEventPayloadSchema = Schema.Struct({
  subject: Schema.String,
  body: Schema.optional(
    Schema.Struct({
      contentType: Schema.Literal("text", "html"),
      content: Schema.String,
    }),
  ),
  start: DateTimeTimeZoneSchema,
  end: DateTimeTimeZoneSchema,
  location: Schema.optional(EventLocationSchema),
  attendees: Schema.optional(Schema.Array(AttendeeSchema)),
  isAllDay: Schema.optional(Schema.Boolean),
  isOnlineMeeting: Schema.optional(Schema.Boolean),
  onlineMeetingProvider: Schema.optional(
    Schema.Literal("unknown", "skypeForBusiness", "skypeForConsumer", "teamsForBusiness"),
  ),
  recurrence: Schema.optional(PatternedRecurrenceSchema),
  importance: Schema.optional(Schema.Literal("low", "normal", "high")),
  sensitivity: Schema.optional(Schema.Literal("normal", "personal", "private", "confidential")),
  showAs: Schema.optional(
    Schema.Literal("free", "tentative", "busy", "oof", "workingElsewhere", "unknown"),
  ),
  reminderMinutesBeforeStart: Schema.optional(Schema.Number),
  isReminderOn: Schema.optional(Schema.Boolean),
  categories: Schema.optional(Schema.Array(Schema.String)),
});

export type CreateEventPayload = Schema.Schema.Type<typeof CreateEventPayloadSchema>;

export const AttendeeAvailabilitySchema = Schema.Struct({
  attendee: Schema.Struct({
    emailAddress: Schema.Struct({
      address: Schema.String,
      name: Schema.optional(Schema.String),
    }),
    type: Schema.optional(Schema.Literal("required", "optional", "resource")),
  }),
  availabilityView: Schema.optional(Schema.String),
  scheduleItems: Schema.optional(
    Schema.Array(
      Schema.Struct({
        isPrivate: Schema.Boolean,
        status: Schema.Literal("free", "tentative", "busy", "oof", "workingElsewhere", "unknown"),
        subject: Schema.optional(Schema.String),
        location: Schema.optional(Schema.String),
        start: DateTimeTimeZoneSchema,
        end: DateTimeTimeZoneSchema,
      }),
    ),
  ),
});

export const FindMeetingTimesRequestSchema = Schema.Struct({
  attendees: Schema.optional(
    Schema.Array(
      Schema.Struct({
        emailAddress: Schema.Struct({
          address: Schema.String,
          name: Schema.optional(Schema.String),
        }),
        type: Schema.optional(Schema.Literal("required", "optional", "resource")),
      }),
    ),
  ),
  timeConstraint: Schema.optional(
    Schema.Struct({
      activityDomain: Schema.optional(
        Schema.Literal("work", "personal", "unrestricted", "unknown"),
      ),
      timeslots: Schema.Array(
        Schema.Struct({
          start: DateTimeTimeZoneSchema,
          end: DateTimeTimeZoneSchema,
        }),
      ),
    }),
  ),
  meetingDuration: Schema.optional(Schema.String),
  maxCandidates: Schema.optional(Schema.Number),
  isOrganizerOptional: Schema.optional(Schema.Boolean),
  returnSuggestionReasons: Schema.optional(Schema.Boolean),
  minimumAttendeePercentage: Schema.optional(Schema.Number),
});

export type FindMeetingTimesRequest = Schema.Schema.Type<typeof FindMeetingTimesRequestSchema>;

export const MeetingTimeSuggestionsResultSchema = Schema.Struct({
  emptySuggestionsReason: Schema.optional(Schema.String),
  meetingTimeSuggestions: Schema.Array(
    Schema.Struct({
      confidence: Schema.Number,
      order: Schema.optional(Schema.Number),
      organizerAvailability: Schema.Literal("free", "tentative", "busy", "oof", "workingElsewhere", "unknown"),
      attendeeAvailability: Schema.Array(AttendeeAvailabilitySchema),
      locations: Schema.optional(Schema.Array(EventLocationSchema)),
      meetingTimeSlot: Schema.Struct({
        start: DateTimeTimeZoneSchema,
        end: DateTimeTimeZoneSchema,
      }),
      suggestionReason: Schema.optional(Schema.String),
    }),
  ),
});

export type MeetingTimeSuggestionsResult = Schema.Schema.Type<typeof MeetingTimeSuggestionsResultSchema>;

