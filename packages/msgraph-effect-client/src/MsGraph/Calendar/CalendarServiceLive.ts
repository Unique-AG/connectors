import { Effect, Layer } from 'effect';
import { DelegatedAuth } from '../Auth/MsGraphAuth';
import {
  toNotFoundOrRateLimit,
  toNotFoundRateLimitOrInvalid,
  toRateLimitOrInvalid,
} from '../Errors/errorNarrowers';
import { MsGraphHttpClient } from '../Http/MsGraphHttpClient';
import type { CalendarEvent, CreateEventPayload, FindMeetingTimesRequest } from '../Schemas/Event';
import { CalendarEventSchema, MeetingTimeSuggestionsResultSchema } from '../Schemas/Event';
import type { ODataParams } from '../Schemas/OData';
import { buildQueryString, ODataPage } from '../Schemas/OData';
import { CalendarService } from './CalendarService';

const CalendarEventPageSchema = ODataPage(CalendarEventSchema);

export const CalendarServiceLive: Layer.Layer<
  CalendarService,
  never,
  MsGraphHttpClient | DelegatedAuth
> = Layer.effect(
  CalendarService,
  Effect.gen(function* () {
    const client = yield* MsGraphHttpClient;

    const listEvents = Effect.fn('CalendarService.listEvents')(
      function* (userId: string, params?: ODataParams<CalendarEvent>) {
        const basePath = `/users/${encodeURIComponent(userId)}/events`;
        const path = params ? `${basePath}${buildQueryString(params)}` : basePath;
        return yield* client
          .get(path, CalendarEventPageSchema)
          .pipe(Effect.mapError(toRateLimitOrInvalid(basePath)));
      },
      Effect.annotateLogs({ service: 'CalendarService', method: 'listEvents' }),
    );

    const getEvent = Effect.fn('CalendarService.getEvent')(
      function* (userId: string, eventId: string) {
        const path = `/users/${encodeURIComponent(userId)}/events/${encodeURIComponent(eventId)}`;
        return yield* client
          .get(path, CalendarEventSchema)
          .pipe(Effect.mapError(toNotFoundOrRateLimit(path)));
      },
      Effect.annotateLogs({ service: 'CalendarService', method: 'getEvent' }),
    );

    const createEvent = Effect.fn('CalendarService.createEvent')(
      function* (userId: string, event: CreateEventPayload) {
        const path = `/users/${encodeURIComponent(userId)}/events`;
        return yield* client
          .post(path, event, CalendarEventSchema)
          .pipe(Effect.mapError(toRateLimitOrInvalid(path)));
      },
      Effect.annotateLogs({ service: 'CalendarService', method: 'createEvent' }),
    );

    const updateEvent = Effect.fn('CalendarService.updateEvent')(
      function* (userId: string, eventId: string, patch: Partial<CreateEventPayload>) {
        const path = `/users/${encodeURIComponent(userId)}/events/${encodeURIComponent(eventId)}`;
        return yield* client
          .patch(path, patch, CalendarEventSchema)
          .pipe(Effect.mapError(toNotFoundRateLimitOrInvalid(path)));
      },
      Effect.annotateLogs({ service: 'CalendarService', method: 'updateEvent' }),
    );

    const deleteEvent = Effect.fn('CalendarService.deleteEvent')(
      function* (userId: string, eventId: string) {
        const path = `/users/${encodeURIComponent(userId)}/events/${encodeURIComponent(eventId)}`;
        return yield* client.delete(path).pipe(Effect.mapError(toNotFoundOrRateLimit(path)));
      },
      Effect.annotateLogs({ service: 'CalendarService', method: 'deleteEvent' }),
    );

    const calendarView = Effect.fn('CalendarService.calendarView')(
      function* (
        userId: string,
        startDateTime: string,
        endDateTime: string,
        params?: ODataParams<CalendarEvent>,
      ) {
        const basePath = `/users/${encodeURIComponent(userId)}/calendarView`;
        const dateParams = `startDateTime=${encodeURIComponent(startDateTime)}&endDateTime=${encodeURIComponent(endDateTime)}`;
        const odataQuery = params ? buildQueryString(params) : '';
        const separator = odataQuery ? '&' : '';
        const queryString = odataQuery
          ? `${odataQuery}${separator}${dateParams}`
          : `?${dateParams}`;

        return yield* client
          .get(`${basePath}${queryString}`, CalendarEventPageSchema)
          .pipe(Effect.mapError(toRateLimitOrInvalid(basePath)));
      },
      Effect.annotateLogs({ service: 'CalendarService', method: 'calendarView' }),
    );

    const findMeetingTimes = Effect.fn('CalendarService.findMeetingTimes')(
      function* (userId: string, request: FindMeetingTimesRequest) {
        const path = `/users/${encodeURIComponent(userId)}/findMeetingTimes`;
        return yield* client
          .post(path, request, MeetingTimeSuggestionsResultSchema)
          .pipe(Effect.mapError(toRateLimitOrInvalid(path)));
      },
      Effect.annotateLogs({ service: 'CalendarService', method: 'findMeetingTimes' }),
    );

    return CalendarService.of({
      listEvents,
      getEvent,
      createEvent,
      updateEvent,
      deleteEvent,
      calendarView,
      findMeetingTimes,
    });
  }).pipe(Effect.withSpan('CalendarServiceLive.initialize')),
);
