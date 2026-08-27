import assert from 'node:assert';
import { Client } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { Temporal } from 'temporal-polyfill';
import * as z from 'zod';
import {
  type CalendarMetricErrorType,
  CalendarMetricsService,
} from '~/features/metrics/calendar-metrics.service';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { ResolveMailboxTimezoneQuery } from '~/features/user-utils/resolve-mailbox-timezone.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { type EventRef, GraphWrittenEventSchema } from './calendar.schemas';
import { eventPath } from './utils/calendar-graph-path';
import {
  calendarLogUser,
  calendarTraceAttrs,
  calendarUserProfileId,
  recoverCalendarGraphError,
} from './utils/calendar-observability';
import { graphEventBody } from './utils/graph-event-body';
import { mapIsoToGraphDateTimeTimeZone } from './utils/map-iso-to-graph-date-time-time-zone';
import { uniqueSmtpAddresses } from './utils/smtp-address.schema';

const GraphExistingEventBodySchema = z.object({
  body: z
    .object({
      content: z.string().optional(),
    })
    .nullish(),
});

export interface UpdateEventCommandInput {
  eventRef: EventRef;
  targetEventId: string;
  subject?: string;
  startDateTime?: string;
  endDateTime?: string;
  attendees?: string[];
  location?: string;
  body?: string;
  isOnlineMeeting?: boolean;
  /**
   * Whether Graph will have notified attendees. Reporting only — Graph decides this from the event
   * itself and there is no flag to suppress it, so setting this false does not make the update
   * silent.
   */
  attendeesWereNotified: boolean;
}

export interface UpdateEventCommandOutput {
  success: boolean;
  message: string;
  eventRef?: EventRef;
  subject?: string | null;
  start?: { dateTime: string; timeZone: string | null };
  end?: { dateTime: string; timeZone: string | null };
  location?: string | null;
  joinUrl?: string | null;
  webLink?: string | null;
  consentRequired?: boolean;
  errorType?: CalendarMetricErrorType;
}

@Injectable()
export class UpdateEventCommand {
  private readonly logger = new Logger(UpdateEventCommand.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getUserProfileQuery: GetUserProfileQuery,
    private readonly resolveMailboxTimezoneQuery: ResolveMailboxTimezoneQuery,
    private readonly calendarMetrics: CalendarMetricsService,
  ) {}

  @Span()
  public async run(
    userProfileId: UserProfileTypeID,
    input: UpdateEventCommandInput,
  ): Promise<UpdateEventCommandOutput> {
    const userProfileIdString = calendarUserProfileId(userProfileId);
    this.logger.debug({
      userProfileId: userProfileIdString,
      calendarId: input.eventRef.calendarId,
      msg: 'update_event started',
    });
    return this.calendarMetrics.measureOperation({ operation: 'update_event' }, () =>
      this.update(userProfileId, userProfileIdString, input),
    );
  }

  private async update(
    userProfileId: UserProfileTypeID,
    userProfileIdString: string,
    input: UpdateEventCommandInput,
  ): Promise<UpdateEventCommandOutput> {
    assert.ok(input.eventRef.calendarId.length > 0, 'eventRef.calendarId must already be set');
    assert.ok(input.targetEventId.length > 0, 'targetEventId must already be set');
    const patch = buildPatch(input);
    const hasTimeChange = input.startDateTime !== undefined || input.endDateTime !== undefined;
    assert.ok(
      Object.keys(patch).length > 0 || hasTimeChange || input.body !== undefined,
      'update must already include at least one field',
    );

    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    calendarTraceAttrs({
      userProfileId: userProfileIdString,
      userProfileEmail: userProfile.email,
      calendarId: input.eventRef.calendarId,
      operation: 'update_event',
    });
    const { ianaTimeZone, outlookTimeZone } =
      await this.resolveMailboxTimezoneQuery.run(userProfileId);
    const client = this.graphClientFactory.createClientForUser(userProfile.id);
    const path = eventPath({
      calendarId: input.eventRef.calendarId,
      eventId: input.targetEventId,
    });
    const startTime =
      input.startDateTime !== undefined
        ? mapIsoToGraphDateTimeTimeZone({
            iso: input.startDateTime,
            ianaTimeZone,
            windowsTimeZone: outlookTimeZone,
          })
        : undefined;
    const endTime =
      input.endDateTime !== undefined
        ? mapIsoToGraphDateTimeTimeZone({
            iso: input.endDateTime,
            ianaTimeZone,
            windowsTimeZone: outlookTimeZone,
          })
        : undefined;

    try {
      const body =
        input.body !== undefined
          ? graphEventBody(input.body, await loadExistingEventHtml(client, path, outlookTimeZone))
          : undefined;
      const raw = await client
        .api(path)
        .header('Prefer', `outlook.timezone="${outlookTimeZone}", IdType="ImmutableId"`)
        .patch({
          ...patch,
          ...(body !== undefined ? { body } : {}),
          ...(startTime !== undefined ? { start: startTime } : {}),
          ...(endTime !== undefined ? { end: endTime } : {}),
        });
      const updated = GraphWrittenEventSchema.parse(raw);
      this.logger.log({
        ...calendarLogUser(userProfileIdString, userProfile.email),
        calendarId: input.eventRef.calendarId,
        msg: 'update_event',
      });
      return {
        success: true,
        message: input.attendeesWereNotified
          ? 'Updated the event. Attendees were notified immediately.'
          : 'Updated the event.',
        eventRef: {
          eventId: updated.id,
          calendarId: input.eventRef.calendarId,
        },
        subject: updated.subject ?? input.subject?.trim() ?? null,
        start: {
          dateTime: updated.start?.dateTime ?? startTime?.dateTime ?? '',
          timeZone: updated.start?.timeZone ?? startTime?.timeZone ?? null,
        },
        end: {
          dateTime: updated.end?.dateTime ?? endTime?.dateTime ?? '',
          timeZone: updated.end?.timeZone ?? endTime?.timeZone ?? null,
        },
        location: updated.location?.displayName ?? input.location?.trim() ?? null,
        joinUrl: updated.onlineMeeting?.joinUrl ?? updated.onlineMeetingUrl ?? null,
        webLink: updated.webLink ?? null,
      };
    } catch (error) {
      return recoverCalendarGraphError({
        error,
        logger: this.logger,
        userProfileId: userProfileIdString,
        userProfileEmail: userProfile.email,
        calendarId: input.eventRef.calendarId,
        operation: 'update_event',
        notFoundMessage:
          'That event was not found. Search again and pass eventRef without changing it.',
        invalidMessage: 'Graph rejected the update. Check the times and fields and try again.',
      });
    }
  }
}

function buildPatch(input: UpdateEventCommandInput): Record<string, unknown> {
  if (input.startDateTime !== undefined && input.endDateTime !== undefined) {
    const start = Temporal.Instant.from(input.startDateTime);
    const end = Temporal.Instant.from(input.endDateTime);
    assert.ok(
      Temporal.Instant.compare(end, start) > 0,
      'endDateTime must already be after startDateTime',
    );
  }
  const attendees =
    input.attendees !== undefined ? uniqueSmtpAddresses(input.attendees) : undefined;
  return {
    ...(input.subject !== undefined && input.subject.trim() !== ''
      ? { subject: input.subject.trim() }
      : {}),
    ...(input.location !== undefined ? { location: { displayName: input.location.trim() } } : {}),
    ...(attendees !== undefined
      ? {
          attendees: attendees.map((address) => ({
            type: 'required',
            emailAddress: { address },
          })),
        }
      : {}),
    ...(input.isOnlineMeeting === true
      ? { isOnlineMeeting: true, onlineMeetingProvider: 'teamsForBusiness' }
      : {}),
  };
}

async function loadExistingEventHtml(
  client: Client,
  path: string,
  outlookTimeZone: string,
): Promise<string | undefined> {
  const existing = GraphExistingEventBodySchema.parse(
    await client
      .api(path)
      .header(
        'Prefer',
        `outlook.timezone="${outlookTimeZone}", IdType="ImmutableId", outlook.body-content-type="html"`,
      )
      .select('body')
      .get(),
  );
  return existing.body?.content;
}
