import { Effect, Layer, Match } from "effect"
import { DelegatedAuth } from "../Auth/MsGraphAuth"
import {
  InvalidRequestError,
  RateLimitedError,
  ResourceNotFoundError,
} from "../Errors/errors"
import type { MsGraphError } from "../Errors/errors"
import { MsGraphHttpClient } from "../Http/MsGraphHttpClient"
import { ODataPage, buildQueryString } from "../Schemas/OData"
import type { ODataParams } from "../Schemas/OData"
import {
  CalendarEventSchema,
  MeetingTimeSuggestionsResultSchema,
} from "../Schemas/Event"
import type { CalendarEvent, CreateEventPayload, FindMeetingTimesRequest } from "../Schemas/Event"
import { CalendarService } from "./CalendarService"

const CalendarEventPageSchema = ODataPage(CalendarEventSchema)

const narrowToRateLimitOrInvalid = Match.type<MsGraphError>().pipe(
  Match.tag("RateLimitedError", (e) => e),
  Match.tag("InvalidRequest", (e) => e),
  Match.orElse(
    (e) =>
      new InvalidRequestError({
        code: e._tag,
        message: "Unexpected error",
        target: undefined,
        details: [],
      }),
  ),
)

const narrowToNotFoundOrRateLimit = Match.type<MsGraphError>().pipe(
  Match.tag("RateLimitedError", (e) => e),
  Match.tag("ResourceNotFound", (e) => e),
  Match.orElse(
    () => new ResourceNotFoundError({ resource: "CalendarEvent", id: "unknown" }),
  ),
)

const narrowToNotFoundRateLimitOrInvalid = Match.type<MsGraphError>().pipe(
  Match.tag("RateLimitedError", (e) => e),
  Match.tag("ResourceNotFound", (e) => e),
  Match.tag("InvalidRequest", (e) => e),
  Match.orElse(
    (e) =>
      new InvalidRequestError({
        code: e._tag,
        message: "Unexpected error",
        target: undefined,
        details: [],
      }),
  ),
)

export const CalendarServiceLive: Layer.Layer<
  CalendarService,
  never,
  MsGraphHttpClient | DelegatedAuth
> = Layer.effect(
  CalendarService,
  Effect.gen(function* () {
    const client = yield* MsGraphHttpClient

    const listEvents = Effect.fn("CalendarService.listEvents")(
      function* (userId: string, params?: ODataParams<CalendarEvent>) {
        const path = params
          ? `/users/${encodeURIComponent(userId)}/events${buildQueryString(params)}`
          : `/users/${encodeURIComponent(userId)}/events`
        return yield* client.get(path, CalendarEventPageSchema).pipe(
          Effect.mapError(narrowToRateLimitOrInvalid),
        )
      },
    )

    const getEvent = Effect.fn("CalendarService.getEvent")(
      function* (userId: string, eventId: string) {
        return yield* client
          .get(
            `/users/${encodeURIComponent(userId)}/events/${encodeURIComponent(eventId)}`,
            CalendarEventSchema,
          )
          .pipe(Effect.mapError(narrowToNotFoundOrRateLimit))
      },
    )

    const createEvent = Effect.fn("CalendarService.createEvent")(
      function* (userId: string, event: CreateEventPayload) {
        return yield* client
          .post(
            `/users/${encodeURIComponent(userId)}/events`,
            event,
            CalendarEventSchema,
          )
          .pipe(Effect.mapError(narrowToRateLimitOrInvalid))
      },
    )

    const updateEvent = Effect.fn("CalendarService.updateEvent")(
      function* (
        userId: string,
        eventId: string,
        patch: Partial<CreateEventPayload>,
      ) {
        return yield* client
          .patch(
            `/users/${encodeURIComponent(userId)}/events/${encodeURIComponent(eventId)}`,
            patch,
            CalendarEventSchema,
          )
          .pipe(Effect.mapError(narrowToNotFoundRateLimitOrInvalid))
      },
    )

    const deleteEvent = Effect.fn("CalendarService.deleteEvent")(
      function* (userId: string, eventId: string) {
        return yield* client
          .delete(
            `/users/${encodeURIComponent(userId)}/events/${encodeURIComponent(eventId)}`,
          )
          .pipe(Effect.mapError(narrowToNotFoundOrRateLimit))
      },
    )

    const calendarView = Effect.fn("CalendarService.calendarView")(
      function* (
        userId: string,
        startDateTime: string,
        endDateTime: string,
        params?: ODataParams<CalendarEvent>,
      ) {
        const dateParams = `startDateTime=${encodeURIComponent(startDateTime)}&endDateTime=${encodeURIComponent(endDateTime)}`
        const odataQuery = params ? buildQueryString(params) : ""
        const separator = odataQuery ? "&" : ""
        const queryString = odataQuery
          ? `${odataQuery}${separator}${dateParams}`
          : `?${dateParams}`

        return yield* client
          .get(
            `/users/${encodeURIComponent(userId)}/calendarView${queryString}`,
            CalendarEventPageSchema,
          )
          .pipe(Effect.mapError(narrowToRateLimitOrInvalid))
      },
    )

    const findMeetingTimes = Effect.fn("CalendarService.findMeetingTimes")(
      function* (userId: string, request: FindMeetingTimesRequest) {
        return yield* client
          .post(
            `/users/${encodeURIComponent(userId)}/findMeetingTimes`,
            request,
            MeetingTimeSuggestionsResultSchema,
          )
          .pipe(Effect.mapError(narrowToRateLimitOrInvalid))
      },
    )

    return CalendarService.of({
      listEvents,
      getEvent,
      createEvent,
      updateEvent,
      deleteEvent,
      calendarView,
      findMeetingTimes,
    })
  }),
)
