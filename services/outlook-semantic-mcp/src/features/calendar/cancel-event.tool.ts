import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { obfuscateEmail } from '~/utils/obfuscate-email';
import { CancelEventCommand } from './cancel-event.command';
import { META } from './cancel-event-tool.meta';
import type { CalendarEventSnapshot } from './get-calendar-event.query';
import { GetCalendarEventQuery } from './get-calendar-event.query';
import { oneLine } from './utils/calendar-display';
import { confirmWrite } from './utils/confirm-write';
import { EventRefSchema } from './utils/event-ref.schema';
import {
  isSeriesOccurrence,
  parseSeriesScope,
  resolveWriteEventId,
  SERIES_SCOPES,
} from './utils/resolve-write-event-id';

const ConfirmSchema = z.object({
  confirmed: z.boolean().meta({
    title: 'Cancel this event',
    description:
      'Confirm to cancel the event. Attendees are notified. This is not a silent delete. Leave unchecked to keep the event.',
  }),
});

const SeriesConfirmSchema = ConfirmSchema.extend({
  applyTo: z.enum(SERIES_SCOPES).meta({
    title: 'How much of the series',
    description:
      'thisOccurrence cancels only this date. entireSeries cancels every date, including this one.',
  }),
});

export const CancelEventInputSchema = z.object({
  eventRef: EventRefSchema.describe(
    'Internal handle from search_calendar_events. Pass it through unchanged. Never display it.',
  ),
  comment: z
    .string()
    .optional()
    .describe('Optional note included on the cancellation sent to attendees.'),
});

export const CancelEventOutputSchema = z.object({
  success: z
    .boolean()
    .describe(
      'True when Graph cancelled the event. False when the user declined, the event was already cancelled or not found, consent is missing, or only the organizer can cancel.',
    ),
  message: z.string().describe('Human-readable summary of the outcome.'),
  consentRequired: z
    .boolean()
    .optional()
    .describe(
      'True when calendar scopes have not been granted yet. The user must reconnect Outlook before calendar tools will work.',
    ),
});

@Injectable()
export class CancelEventTool {
  private readonly logger = new Logger(CancelEventTool.name);

  public constructor(
    private readonly getCalendarEventQuery: GetCalendarEventQuery,
    private readonly cancelEventCommand: CancelEventCommand,
  ) {}

  @Tool({
    name: 'cancel_event',
    title: 'Cancel Event',
    description:
      'Cancel an Outlook calendar event. This notifies attendees and is not a silent delete. Pass eventRef from search_calendar_events unchanged. Only the organizer can cancel. For a recurring meeting the user chooses this occurrence or the whole series in the confirmation. If consentRequired is true, ask the user to reconnect Outlook.',
    parameters: CancelEventInputSchema,
    outputSchema: CancelEventOutputSchema,
    annotations: {
      title: 'Cancel Event',
      readOnlyHint: false,
      destructiveHint: true,
      idempotentHint: false,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async cancelEvent(
    input: z.infer<typeof CancelEventInputSchema>,
    context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.infer<typeof CancelEventOutputSchema>> {
    const parsed = CancelEventInputSchema.parse(input);
    const userProfileId = extractUserProfileId(request);
    const loaded = await this.getCalendarEventQuery.run(userProfileId, {
      eventRef: parsed.eventRef,
    });
    if (loaded.success !== true || loaded.event === undefined) {
      return { success: false, message: loaded.message, consentRequired: loaded.consentRequired };
    }
    const snapshot = loaded.event;
    if (snapshot.isCancelled) {
      return { success: false, message: 'That event is already cancelled.' };
    }
    const confirmation = await confirmWrite({
      context,
      schema: isSeriesOccurrence(snapshot.type) ? SeriesConfirmSchema : ConfirmSchema,
      message: elicitMessage(parsed, snapshot),
      logger: this.logger,
      operation: 'cancel_event',
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
        msg: 'cancel_event elicit cancelled',
      });
      return { success: false, message: 'Cancellation was declined. The event was left in place.' };
    }
    const applyTo = parseSeriesScope(confirmation.content);
    this.logger.debug({
      userProfileId: userProfileId.toString(),
      mailbox: obfuscateEmail(parsed.eventRef.mailbox),
      calendarId: parsed.eventRef.calendarId,
      applyTo,
      msg: 'cancel_event series scope',
    });
    if (applyTo === 'entireSeries' && snapshot.seriesMasterId === null) {
      return {
        success: false,
        message: 'This event has no series master. Search again and cancel this occurrence only.',
      };
    }
    return this.cancelEventCommand.run(userProfileId, {
      eventRef: parsed.eventRef,
      targetEventId: resolveWriteEventId({
        eventId: parsed.eventRef.eventId,
        seriesMasterId: snapshot.seriesMasterId,
        applyTo,
      }),
      comment: parsed.comment,
      attendeesWereNotified: snapshot.attendeeCount > 0,
    });
  }
}

function elicitMessage(
  input: z.infer<typeof CancelEventInputSchema>,
  snapshot: CalendarEventSnapshot,
): string {
  const series =
    snapshot.type === 'seriesMaster'
      ? 'This is the series master — cancellation applies to every date.'
      : isSeriesOccurrence(snapshot.type)
        ? 'This is one date in a series. Choose this occurrence or the entire series.'
        : 'This is a single event.';
  const comment =
    input.comment !== undefined && oneLine(input.comment) !== ''
      ? `Comment: ${oneLine(input.comment)}.`
      : undefined;
  const notify =
    snapshot.attendeeCount > 0
      ? 'Attendees will be notified. This is not a silent delete.'
      : 'No attendees will be notified.';
  return [
    `Cancel this event on mailbox ${snapshot.mailbox}?`,
    series,
    `Title: ${oneLine(snapshot.subject ?? '(no title)')}.`,
    snapshot.start !== null ? `When: ${snapshot.start.dateTime}.` : undefined,
    comment,
    notify,
  ]
    .filter((line) => line !== undefined)
    .join('\n');
}
