import { Effect, Layer, pipe } from "effect"
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

const narrowToRateLimitOrInvalid = (
  error: MsGraphError,
): RateLimitedError | InvalidRequestError => {
  if (error._tag === "RateLimitedError") return error as RateLimitedError
  if (error._tag === "InvalidRequest") return error as InvalidRequestError
  return new InvalidRequestError({
    code: error._tag,
    message: "Unexpected error",
    target: undefined,
    details: [],
  })
}

const narrowToNotFoundOrRateLimit = (
  error: MsGraphError,
): ResourceNotFoundError | RateLimitedError => {
  if (error._tag === "RateLimitedError") return error as RateLimitedError
  if (error._tag === "ResourceNotFound") return error as ResourceNotFoundError
  return new ResourceNotFoundError({ resource: "CalendarEvent", id: "unknown" })
}

const narrowToNotFoundRateLimitOrInvalid = (
  error: MsGraphError,
): ResourceNotFoundError | RateLimitedError | InvalidRequestError => {
  if (error._tag === "RateLimitedError") return error as RateLimitedError
  if (error._tag === "ResourceNotFound") return error as ResourceNotFoundError
  if (error._tag === "InvalidRequest") return error as InvalidRequestError
  return new InvalidRequestError({
    code: error._tag,
    message: "Unexpected error",
    target: undefined,
    details: [],
  })
}

export const CalendarServiceLive: Layer.Layer<
  CalendarService,
  never,
  MsGraphHttpClient | DelegatedAuth
> = Layer.effect(
  CalendarService,
  Effect.gen(function* () {
    const client = yield* MsGraphHttpClient

    const listEvents = (userId: string, params?: ODataParams<CalendarEvent>) =>
      pipe(
        client.get(
          `/users/${encodeURIComponent(userId)}/events${params ? buildQueryString(params) : ""}`,
          CalendarEventPageSchema,
        ),
        Effect.mapError(narrowToRateLimitOrInvalid),
      )

    const getEvent = (userId: string, eventId: string) =>
      pipe(
        client.get(
          `/users/${encodeURIComponent(userId)}/events/${encodeURIComponent(eventId)}`,
          CalendarEventSchema,
        ),
        Effect.mapError(narrowToNotFoundOrRateLimit),
      )

    const createEvent = (userId: string, event: CreateEventPayload) =>
      pipe(
        client.post(
          `/users/${encodeURIComponent(userId)}/events`,
          event,
          CalendarEventSchema,
        ),
        Effect.mapError(narrowToRateLimitOrInvalid),
      )

    const updateEvent = (
      userId: string,
      eventId: string,
      patch: Partial<CreateEventPayload>,
    ) =>
      pipe(
        client.patch(
          `/users/${encodeURIComponent(userId)}/events/${encodeURIComponent(eventId)}`,
          patch,
          CalendarEventSchema,
        ),
        Effect.mapError(narrowToNotFoundRateLimitOrInvalid),
      )

    const deleteEvent = (userId: string, eventId: string) =>
      pipe(
        client.delete(
          `/users/${encodeURIComponent(userId)}/events/${encodeURIComponent(eventId)}`,
        ),
        Effect.mapError(narrowToNotFoundOrRateLimit),
      )

    const calendarView = (
      userId: string,
      startDateTime: string,
      endDateTime: string,
      params?: ODataParams<CalendarEvent>,
    ) => {
      const dateParams = `startDateTime=${encodeURIComponent(startDateTime)}&endDateTime=${encodeURIComponent(endDateTime)}`
      const odataQuery = params ? buildQueryString(params) : ""
      const separator = odataQuery ? "&" : ""
      const queryString = odataQuery
        ? `${odataQuery}${separator}${dateParams}`
        : `?${dateParams}`

      return pipe(
        client.get(
          `/users/${encodeURIComponent(userId)}/calendarView${queryString}`,
          CalendarEventPageSchema,
        ),
        Effect.mapError(narrowToRateLimitOrInvalid),
      )
    }

    const findMeetingTimes = (userId: string, request: FindMeetingTimesRequest) =>
      pipe(
        client.post(
          `/users/${encodeURIComponent(userId)}/findMeetingTimes`,
          request,
          MeetingTimeSuggestionsResultSchema,
        ),
        Effect.mapError(narrowToRateLimitOrInvalid),
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
