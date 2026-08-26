import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { Temporal } from 'temporal-polyfill';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { obfuscateEmail } from '~/utils/obfuscate-email';
import { offsetDateTime } from '~/utils/relative-range';
import { type CalendarSummary, GetCalendarQuery } from './get-calendar.query';
import type { CalendarEventSnapshot } from './get-calendar-event.query';
import { GetCalendarEventQuery } from './get-calendar-event.query';
import { UpdateEventCommand } from './update-event.command';
import { META } from './update-event-tool.meta';
import { describeCalendar, GraphDateTimeSchema, oneLine } from './utils/calendar-display';
import { confirmWrite } from './utils/confirm-write';
import { EventRefSchema } from './utils/event-ref.schema';
import {
  isSeriesOccurrence,
  parseSeriesScope,
  resolveWriteEventId,
  SERIES_SCOPES,
} from './utils/resolve-write-event-id';
import { smtpAddress } from './utils/smtp-address.schema';

const ConfirmSchema = z.object({
  confirmed: z.boolean().meta({
    title: 'Apply this update',
    description:
      'Confirm to update the event. If it has attendees, they are notified immediately. Leave unchecked to cancel.',
  }),
});

const SeriesConfirmSchema = ConfirmSchema.extend({
  applyTo: z.enum(SERIES_SCOPES).meta({
    title: 'How much of the series',
    description:
      'thisOccurrence updates only this date. entireSeries updates every date, including this one.',
  }),
});

export const UpdateEventInputSchema = z
  .object({
    eventRef: EventRefSchema.describe(
      'Internal handle from search_calendar_events. Pass it through unchanged. Never display it.',
    ),
    subject: z
      .string()
      .trim()
      .min(1)
      .optional()
      .describe('Replacement title. Omit to leave the title unchanged.'),
    startDateTime: offsetDateTime(
      'Replacement inclusive start, e.g. 2026-08-26T09:00:00+02:00. Offset is required. Omit to leave start unchanged.',
    ).optional(),
    endDateTime: offsetDateTime(
      'Replacement exclusive end, e.g. 2026-08-26T09:30:00+02:00. Offset is required. Omit to leave end unchanged. Must be after startDateTime when both are set.',
    ).optional(),
    attendees: z
      .array(smtpAddress('SMTP address of a required attendee. Replaces the entire attendee list.'))
      .max(20)
      .optional()
      .describe(
        'Replacement required-attendee list, maximum 20. Omit to leave attendees unchanged. An empty list removes every attendee. Notifications are sent immediately.',
      ),
    location: z
      .string()
      .optional()
      .describe('Replacement location display name. Omit to leave location unchanged.'),
    body: z
      .string()
      .optional()
      .describe('Replacement plain-text agenda or notes. Omit to leave the body unchanged.'),
    isOnlineMeeting: z
      .literal(true)
      .optional()
      .describe('If true, add a Teams meeting. Omit to leave the online-meeting flag unchanged.'),
  })
  .superRefine((value, ctx) => {
    const hasChange =
      value.subject !== undefined ||
      value.startDateTime !== undefined ||
      value.endDateTime !== undefined ||
      value.attendees !== undefined ||
      value.location !== undefined ||
      value.body !== undefined ||
      value.isOnlineMeeting === true;
    if (!hasChange) {
      ctx.addIssue({
        code: 'custom',
        message: 'Provide at least one field to change.',
        path: ['subject'],
      });
    }
    const start = parseInstant(value.startDateTime, 'startDateTime', ctx);
    const end = parseInstant(value.endDateTime, 'endDateTime', ctx);
    if (start !== undefined && end !== undefined && Temporal.Instant.compare(end, start) <= 0) {
      ctx.addIssue({
        code: 'custom',
        message: 'endDateTime must be after startDateTime.',
        path: ['endDateTime'],
      });
    }
  });

function parseInstant(
  raw: string | undefined,
  path: 'startDateTime' | 'endDateTime',
  ctx: z.RefinementCtx,
): Temporal.Instant | undefined {
  if (raw === undefined) {
    return undefined;
  }
  try {
    return Temporal.Instant.from(raw);
  } catch {
    ctx.addIssue({
      code: 'custom',
      message: 'Must be a valid offset-bearing timestamp.',
      path: [path],
    });
    return undefined;
  }
}

export const UpdateEventOutputSchema = z.object({
  success: z
    .boolean()
    .describe(
      'True when Graph updated the event. False when the user cancelled, the event was not found, Graph rejected the update, consent is missing, or the mailbox cannot be written.',
    ),
  message: z.string().describe('Human-readable summary of the outcome.'),
  eventRef: EventRefSchema.optional().describe(
    'Internal handle of the updated event. Never display it.',
  ),
  subject: z.string().nullable().optional().describe('Title after the update.'),
  start: GraphDateTimeSchema.optional().describe('Start after the update.'),
  end: GraphDateTimeSchema.optional().describe('End after the update.'),
  location: z.string().nullable().optional().describe('Location after the update, or null.'),
  joinUrl: z.string().nullable().optional().describe('Teams join URL when present, or null.'),
  webLink: z
    .string()
    .nullable()
    .optional()
    .describe('Outlook web link for the updated event. This is the user-facing URL.'),
  consentRequired: z
    .boolean()
    .optional()
    .describe(
      'True when calendar scopes have not been granted yet. The user must reconnect Outlook before calendar tools will work.',
    ),
});

@Injectable()
export class UpdateEventTool {
  private readonly logger = new Logger(UpdateEventTool.name);

  public constructor(
    private readonly getCalendarEventQuery: GetCalendarEventQuery,
    private readonly getCalendarQuery: GetCalendarQuery,
    private readonly updateEventCommand: UpdateEventCommand,
  ) {}

  @Tool({
    name: 'update_event',
    title: 'Update Event',
    description:
      'Update an existing Outlook calendar event. Pass eventRef from search_calendar_events unchanged. There is no draft — attendees are notified immediately after the user confirms. For a recurring meeting the user chooses this occurrence or the whole series in the confirmation. startDateTime and endDateTime must include a timezone offset. If consentRequired is true, ask the user to reconnect Outlook.',
    parameters: UpdateEventInputSchema,
    outputSchema: UpdateEventOutputSchema,
    annotations: {
      title: 'Update Event',
      readOnlyHint: false,
      destructiveHint: true,
      idempotentHint: false,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async updateEvent(
    input: z.infer<typeof UpdateEventInputSchema>,
    context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.infer<typeof UpdateEventOutputSchema>> {
    const parsed = UpdateEventInputSchema.parse(input);
    const userProfileId = extractUserProfileId(request);
    const loaded = await this.getCalendarEventQuery.run(userProfileId, {
      eventRef: parsed.eventRef,
    });
    if (loaded.success !== true || loaded.event === undefined) {
      return { success: false, message: loaded.message, consentRequired: loaded.consentRequired };
    }
    const snapshot = loaded.event;
    const loadedCalendar = await this.getCalendarQuery.run(userProfileId, {
      calendarRef: {
        calendarId: snapshot.calendarId,
        mailbox: snapshot.mailbox,
      },
    });
    if (loadedCalendar.success !== true || loadedCalendar.calendar === undefined) {
      return {
        success: false,
        message: loadedCalendar.message,
        consentRequired: loadedCalendar.consentRequired,
      };
    }
    const confirmation = await confirmWrite({
      context,
      schema: isSeriesOccurrence(snapshot.type) ? SeriesConfirmSchema : ConfirmSchema,
      message: elicitMessage(parsed, snapshot, loadedCalendar.calendar),
      logger: this.logger,
      operation: 'update_event',
      userProfileId: userProfileId.toString(),
    });
    if (confirmation.status === 'unavailable') {
      return { success: false, message: confirmation.message };
    }
    if (confirmation.status !== 'accepted' || confirmation.content.confirmed !== true) {
      this.logger.debug({
        userProfileId: userProfileId.toString(),
        mailbox: obfuscateEmail(parsed.eventRef.mailbox),
        calendarId: parsed.eventRef.calendarId,
        msg: 'update_event elicit cancelled',
      });
      return { success: false, message: 'Event update was cancelled. No attendees were notified.' };
    }
    const applyTo = parseSeriesScope(confirmation.content);
    this.logger.debug({
      userProfileId: userProfileId.toString(),
      mailbox: obfuscateEmail(parsed.eventRef.mailbox),
      calendarId: parsed.eventRef.calendarId,
      applyTo,
      msg: 'update_event series scope',
    });
    if (applyTo === 'entireSeries' && snapshot.seriesMasterId === null) {
      return {
        success: false,
        message: 'This event has no series master. Search again and update this occurrence only.',
      };
    }
    return this.updateEventCommand.run(userProfileId, {
      eventRef: parsed.eventRef,
      targetEventId: resolveWriteEventId({
        eventId: parsed.eventRef.eventId,
        seriesMasterId: snapshot.seriesMasterId,
        applyTo,
      }),
      subject: parsed.subject,
      startDateTime: parsed.startDateTime,
      endDateTime: parsed.endDateTime,
      attendees: parsed.attendees,
      location: parsed.location,
      body: parsed.body,
      isOnlineMeeting: parsed.isOnlineMeeting,
      attendeesWereNotified:
        snapshot.attendeeCount > 0 ||
        (parsed.attendees !== undefined && parsed.attendees.length > 0),
    });
  }
}

function elicitMessage(
  input: z.infer<typeof UpdateEventInputSchema>,
  snapshot: CalendarEventSnapshot,
  calendar: CalendarSummary,
): string {
  const series =
    snapshot.type === 'seriesMaster'
      ? 'This is the series master — the update applies to every date.'
      : isSeriesOccurrence(snapshot.type)
        ? 'This is one date in a series. Choose this occurrence or the entire series.'
        : 'This is a single event.';
  const current = `Current title: ${oneLine(snapshot.subject ?? '(no title)')}.`;
  const changes = [
    input.subject !== undefined ? `New title: ${oneLine(input.subject)}.` : undefined,
    input.startDateTime !== undefined || input.endDateTime !== undefined
      ? `New when: ${oneLine(input.startDateTime ?? 'unchanged')} to ${oneLine(input.endDateTime ?? 'unchanged')}.`
      : undefined,
    input.attendees !== undefined
      ? input.attendees.length > 0
        ? `Replace attendees with: ${input.attendees.join(', ')}.`
        : 'Remove every attendee.'
      : undefined,
    input.location !== undefined ? `New location: ${oneLine(input.location)}.` : undefined,
    input.body !== undefined ? 'Replace the agenda text.' : undefined,
    input.isOnlineMeeting === true ? 'Add a Teams meeting.' : undefined,
  ].filter((line) => line !== undefined);
  const notify =
    snapshot.attendeeCount > 0 || (input.attendees !== undefined && input.attendees.length > 0)
      ? 'Attendees will be notified immediately.'
      : 'No attendees will be notified.';
  return [
    'Update this event?',
    `Calendar: ${describeCalendar(calendar)}`,
    series,
    current,
    ...changes,
    notify,
  ].join('\n');
}
