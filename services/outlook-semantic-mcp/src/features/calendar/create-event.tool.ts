import { randomUUID } from 'node:crypto';
import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { Temporal } from 'temporal-polyfill';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { obfuscateEmail } from '~/utils/obfuscate-email';
import { offsetDateTime } from '~/utils/relative-range';
import { CreateEventCommand } from './create-event.command';
import { META } from './create-event-tool.meta';
import { type CalendarSummary, GetCalendarQuery } from './get-calendar.query';
import { describeCalendar, formatDisplayWhen, oneLine } from './utils/calendar-display';
import { ConsentRequiredSchema, EventDateTimeSchema } from './utils/calendar-output.schema';
import { CalendarRefSchema } from './utils/calendar-ref.schema';
import { ConfirmSchema, confirmWrite } from './utils/confirm-write';
import { EventRefSchema } from './utils/event-ref.schema';
import { smtpAddress } from './utils/smtp-address.schema';

export const CreateEventInputSchema = z
  .object({
    subject: z.string().min(1).describe('Event title. Shown to attendees on the invitation.'),
    startDateTime: offsetDateTime(
      'Inclusive start, e.g. 2026-08-26T09:00:00+02:00. Offset is required.',
    ),
    endDateTime: offsetDateTime(
      'Exclusive end, e.g. 2026-08-26T09:30:00+02:00. Offset is required. Must be after startDateTime.',
    ),
    attendees: z
      .array(smtpAddress('SMTP address of a required attendee. Invitations are sent immediately.'))
      .max(20)
      .optional()
      .describe(
        'Required attendees. Maximum 20. Omit for an appointment with no invitations. Invitations are sent as soon as the event is created.',
      ),
    location: z.string().optional().describe('Optional location display name.'),
    body: z.string().optional().describe('Optional plain-text agenda or notes.'),
    isOnlineMeeting: z
      .boolean()
      .optional()
      .describe('If true, create a Teams meeting and return a join URL.'),
    calendarRef: CalendarRefSchema.optional().describe(
      'Which calendar to create on. Take calendarRef from list_calendars and pass it through unchanged — never assemble one yourself. Omit to use the signed-in user default calendar.',
    ),
    transactionId: z
      .string()
      .min(1)
      .max(32)
      .optional()
      .describe(
        'Idempotency key, at most 32 characters. Reuse the same value if this create is retried so Graph does not double-book.',
      ),
  })
  .superRefine((value, ctx) => {
    try {
      const start = Temporal.Instant.from(value.startDateTime);
      const end = Temporal.Instant.from(value.endDateTime);
      if (Temporal.Instant.compare(end, start) <= 0) {
        ctx.addIssue({
          code: 'custom',
          message: 'endDateTime must be after startDateTime.',
          path: ['endDateTime'],
        });
      }
    } catch {
      ctx.addIssue({
        code: 'custom',
        message: 'startDateTime and endDateTime must be valid offset-bearing timestamps.',
        path: ['endDateTime'],
      });
    }
  });

export const CreateEventOutputSchema = z.object({
  success: z
    .boolean()
    .describe(
      'True when Graph created the event. False when the user cancelled, the calendar was not found, Graph rejected the event, consent is missing, or the mailbox cannot be written.',
    ),
  message: z.string().describe('Human-readable summary of the outcome.'),
  eventRef: EventRefSchema.optional().describe(
    'Internal handle of the created event. Never display it.',
  ),
  subject: z.string().nullable().optional().describe('Title of the created event.'),
  start: EventDateTimeSchema.optional().describe('Created event start.'),
  end: EventDateTimeSchema.optional().describe('Created event end.'),
  location: z.string().nullable().optional().describe('Location of the created event, or null.'),
  joinUrl: z
    .string()
    .nullable()
    .optional()
    .describe('Teams join URL when isOnlineMeeting was true, or null.'),
  webLink: z
    .string()
    .nullable()
    .optional()
    .describe('Outlook web link for the created event. This is the user-facing URL.'),
  transactionId: z
    .string()
    .optional()
    .describe('Idempotency key sent to Graph. Pass it again if this create is retried.'),
  consentRequired: ConsentRequiredSchema.optional(),
});

@Injectable()
export class CreateEventTool {
  private readonly logger = new Logger(CreateEventTool.name);

  public constructor(
    private readonly getCalendarQuery: GetCalendarQuery,
    private readonly createEventCommand: CreateEventCommand,
  ) {}

  @Tool({
    name: 'create_event',
    title: 'Create Event',
    description:
      'Create an Outlook calendar event. There is no draft state — if attendees are included, invitations are sent immediately after the user confirms. startDateTime and endDateTime must include a timezone offset. To create on a shared calendar, call list_calendars and pass that calendar calendarRef through unchanged; omit calendarRef for the signed-in user default calendar. If you retry this create, pass the same transactionId. If consentRequired is true, ask the user to reconnect Outlook.',
    parameters: CreateEventInputSchema,
    outputSchema: CreateEventOutputSchema,
    annotations: {
      title: 'Create Event',
      readOnlyHint: false,
      destructiveHint: true,
      idempotentHint: false,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async createEvent(
    input: z.infer<typeof CreateEventInputSchema>,
    context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.infer<typeof CreateEventOutputSchema>> {
    const parsed = CreateEventInputSchema.parse(input);
    const userProfileId = extractUserProfileId(request);
    const transactionId = parsed.transactionId ?? randomUUID().replaceAll('-', '');
    // Resolve first so the confirmation names the real calendar instead of an opaque id, and so
    // the command receives a concrete ref rather than resolving the default a second time.
    const loaded = await this.getCalendarQuery.run(userProfileId, {
      calendarRef: parsed.calendarRef,
    });
    if (loaded.success !== true || loaded.calendar === undefined) {
      return {
        success: false,
        message: loaded.message,
        transactionId,
        consentRequired: loaded.consentRequired,
      };
    }
    const calendar = loaded.calendar;
    if (!calendar.canEdit) {
      this.logger.debug({
        userProfileId: userProfileId.toString(),
        mailbox: obfuscateEmail(calendar.mailbox),
        calendarId: calendar.calendarId,
        msg: 'create_event rejected read-only calendar',
      });
      return {
        success: false,
        message: `Cannot create on ${describeCalendar(calendar)} — it is read-only. Choose a calendar with canEdit true from list_calendars.`,
        transactionId,
      };
    }
    const confirmation = await confirmWrite({
      context,
      schema: ConfirmSchema,
      message: elicitMessage(parsed, calendar),
      logger: this.logger,
      operation: 'create_event',
      userProfileId: userProfileId.toString(),
    });
    if (confirmation.status === 'unavailable') {
      return { success: false, message: confirmation.message, transactionId };
    }
    if (confirmation.status !== 'accepted') {
      this.logger.debug({
        userProfileId: userProfileId.toString(),
        transactionId,
        msg: 'create_event elicit cancelled',
      });
      return {
        success: false,
        message: 'Event creation was cancelled. No invitations were sent.',
        transactionId,
      };
    }
    return this.createEventCommand.run(userProfileId, {
      ...parsed,
      calendarRef: { calendarId: calendar.calendarId, mailbox: calendar.mailbox },
      transactionId,
    });
  }
}

function elicitMessage(
  input: z.infer<typeof CreateEventInputSchema>,
  calendar: CalendarSummary,
): string {
  const attendees =
    input.attendees !== undefined && input.attendees.length > 0
      ? `Attendees: ${input.attendees.join(', ')}. Invitations will be sent immediately.`
      : 'Attendees: none. This is an appointment, not an invitation.';
  const location =
    input.location !== undefined && oneLine(input.location) !== ''
      ? `Location: ${oneLine(input.location)}.`
      : undefined;
  const teams = input.isOnlineMeeting === true ? 'A Teams meeting will be created.' : undefined;
  return [
    'Create this event?',
    `Calendar: ${describeCalendar(calendar)}`,
    `Title: ${oneLine(input.subject)}`,
    `When: ${formatDisplayWhen(input.startDateTime, input.endDateTime) ?? `${input.startDateTime} to ${input.endDateTime}`}`,
    attendees,
    location,
    teams,
  ]
    .filter((line) => line !== undefined)
    .join('\n');
}
