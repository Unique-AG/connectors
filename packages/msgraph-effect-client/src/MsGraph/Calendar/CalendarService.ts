import { Effect, ServiceMap } from 'effect';
import type {
  InvalidRequestError,
  RateLimitedError,
  ResourceNotFoundError,
} from '../Errors/errors';
import type {
  CalendarEvent,
  CreateEventPayload,
  FindMeetingTimesRequest,
  MeetingTimeSuggestionsResult,
} from '../Schemas/Event';
import type { ODataPageType, ODataParams } from '../Schemas/OData';

export class CalendarService extends ServiceMap.Service<
  CalendarService,
  {
    readonly listEvents: (
      userId: string,
      params?: ODataParams<CalendarEvent>,
    ) => Effect.Effect<ODataPageType<CalendarEvent>, RateLimitedError | InvalidRequestError>;

    readonly getEvent: (
      userId: string,
      eventId: string,
    ) => Effect.Effect<CalendarEvent, ResourceNotFoundError | RateLimitedError>;

    readonly createEvent: (
      userId: string,
      event: CreateEventPayload,
    ) => Effect.Effect<CalendarEvent, RateLimitedError | InvalidRequestError>;

    readonly updateEvent: (
      userId: string,
      eventId: string,
      patch: Partial<CreateEventPayload>,
    ) => Effect.Effect<
      CalendarEvent,
      ResourceNotFoundError | RateLimitedError | InvalidRequestError
    >;

    readonly deleteEvent: (
      userId: string,
      eventId: string,
    ) => Effect.Effect<void, ResourceNotFoundError | RateLimitedError>;

    readonly calendarView: (
      userId: string,
      startDateTime: string,
      endDateTime: string,
      params?: ODataParams<CalendarEvent>,
    ) => Effect.Effect<ODataPageType<CalendarEvent>, RateLimitedError | InvalidRequestError>;

    readonly findMeetingTimes: (
      userId: string,
      request: FindMeetingTimesRequest,
    ) => Effect.Effect<MeetingTimeSuggestionsResult, RateLimitedError | InvalidRequestError>;
  }
>()('MsGraph/CalendarService') {}
