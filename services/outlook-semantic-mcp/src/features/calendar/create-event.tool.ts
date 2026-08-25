import { randomUUID } from 'node:crypto';
import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { Temporal } from 'temporal-polyfill';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { CreateEventCommand } from './create-event.command';
import { META } from './create-event-tool.meta';
import { EventRefSchema } from './utils/event-ref.schema';
import { offsetDateTime } from './utils/offset-date-time.schema';
import { smtpAddress } from './utils/smtp-address.schema';

const ConfirmSchema = z.object({
  confirmed: z.boolean().meta({
    title: 'Create this event',
    description:
      'Confirm to create the event. If there are attendees, invitations are sent immediately. Leave unchecked to cancel.',
  }),
});

const DateTimeSchema = z.object({
  dateTime: z
    .string()
    .describe('Local date and time of the boundary as returned by Graph, without a trailing Z.'),
  timeZone: z
    .string()
    .nullable()
    .describe('Windows or IANA timezone Graph attached to this boundary, or null if omitted.'),
});

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
    mailbox: smtpAddress(
      'SMTP address of the mailbox to create on. Omit for the signed-in user. For a delegated calendar, use that mailbox together with its calendarId.',
    ).optional(),
    calendarId: z
      .string()
      .min(1)
      .optional()
      .describe(
        'Internal calendar ID from list_calendars. Omit to use the mailbox default calendar. Never display it.',
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
  start: DateTimeSchema.optional().describe('Created event start.'),
  end: DateTimeSchema.optional().describe('Created event end.'),
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
  consentRequired: z
    .boolean()
    .optional()
    .describe(
      'True when calendar scopes have not been granted yet. The user must reconnect Outlook before calendar tools will work.',
    ),
});

@Injectable()
export class CreateEventTool {
  public constructor(private readonly createEventCommand: CreateEventCommand) {}

  @Tool({
    name: 'create_event',
    title: 'Create Event',
    description:
      'Create an Outlook calendar event. There is no draft state — if attendees are included, invitations are sent immediately after the user confirms. startDateTime and endDateTime must include a timezone offset. Use calendarId from list_calendars for a specific or delegated calendar; omit it for the mailbox default calendar. If you retry this create, pass the same transactionId. If consentRequired is true, ask the user to reconnect Outlook.',
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
    const transactionId = parsed.transactionId ?? randomUUID().replaceAll('-', '');
    const confirmation = await context.elicit(ConfirmSchema, elicitMessage(parsed));
    if (confirmation.action !== 'accept' || confirmation.content.confirmed !== true) {
      return {
        success: false,
        message: 'Event creation was cancelled. No invitations were sent.',
        transactionId,
      };
    }
    return this.createEventCommand.run(extractUserProfileId(request), {
      ...parsed,
      transactionId,
    });
  }
}

function elicitMessage(input: z.infer<typeof CreateEventInputSchema>): string {
  const mailbox =
    input.mailbox !== undefined ? `mailbox ${input.mailbox}` : 'your mailbox (the signed-in user)';
  const calendar =
    input.calendarId !== undefined
      ? 'a specific calendar from list_calendars'
      : 'the default calendar';
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
    `Create this event on ${mailbox}, ${calendar}?`,
    `Title: ${oneLine(input.subject)}`,
    `When: ${input.startDateTime} to ${input.endDateTime}`,
    attendees,
    location,
    teams,
  ]
    .filter((line) => line !== undefined)
    .join('\n');
}

function oneLine(value: string): string {
  return value.replaceAll(/\s+/g, ' ').trim();
}
