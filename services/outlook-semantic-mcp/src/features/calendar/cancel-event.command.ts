import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import {
  type CalendarMetricErrorType,
  CalendarMetricsService,
} from '~/features/metrics/calendar-metrics.service';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { obfuscateEmail } from '~/utils/obfuscate-email';
import type { EventRef } from './calendar.schemas';
import { eventCancelPath } from './utils/calendar-graph-path';
import {
  calendarTraceAttrs,
  calendarUserProfileId,
  recoverCalendarGraphError,
} from './utils/calendar-observability';
import { SmtpAddressSchema } from './utils/smtp-address.schema';

export interface CancelEventCommandInput {
  eventRef: EventRef;
  targetEventId: string;
  comment?: string;
  /** Whether the cancellation notifies attendees. Reporting only; cancel always notifies. */
  attendeesWereNotified: boolean;
}

export interface CancelEventCommandOutput {
  success: boolean;
  message: string;
  consentRequired?: boolean;
  errorType?: CalendarMetricErrorType;
}

@Injectable()
export class CancelEventCommand {
  private readonly logger = new Logger(CancelEventCommand.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getUserProfileQuery: GetUserProfileQuery,
    private readonly calendarMetrics: CalendarMetricsService,
  ) {}

  @Span()
  public async run(
    userProfileId: UserProfileTypeID,
    input: CancelEventCommandInput,
  ): Promise<CancelEventCommandOutput> {
    const userProfileIdString = calendarUserProfileId(userProfileId);
    this.logger.debug({
      userProfileId: userProfileIdString,
      mailbox: obfuscateEmail(input.eventRef.mailbox),
      calendarId: input.eventRef.calendarId,
      msg: 'cancel_event started',
    });
    calendarTraceAttrs({
      userProfileId: userProfileIdString,
      mailbox: input.eventRef.mailbox,
      calendarId: input.eventRef.calendarId,
      operation: 'cancel_event',
    });
    return this.calendarMetrics.measureOperation({ operation: 'cancel_event' }, () =>
      this.cancel(userProfileId, userProfileIdString, input),
    );
  }

  private async cancel(
    userProfileId: UserProfileTypeID,
    userProfileIdString: string,
    input: CancelEventCommandInput,
  ): Promise<CancelEventCommandOutput> {
    assert.ok(
      SmtpAddressSchema.safeParse(input.eventRef.mailbox).success,
      'eventRef.mailbox must already be an SMTP address',
    );
    assert.ok(input.eventRef.calendarId.length > 0, 'eventRef.calendarId must already be set');
    assert.ok(input.targetEventId.length > 0, 'targetEventId must already be set');

    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    const mailbox = input.eventRef.mailbox;
    const client = this.graphClientFactory.createClientForUser(userProfile.id);
    const path = eventCancelPath({
      mailboxEmail: mailbox,
      calendarId: input.eventRef.calendarId,
      eventId: input.targetEventId,
    });
    const comment = input.comment?.trim();

    try {
      await client
        .api(path)
        .header('Prefer', 'IdType="ImmutableId"')
        .post({
          ...(comment !== undefined && comment !== '' ? { comment } : {}),
        });
      this.logger.log({
        userProfileId: userProfileIdString,
        mailbox: obfuscateEmail(mailbox),
        calendarId: input.eventRef.calendarId,
        msg: 'cancel_event',
      });
      return {
        success: true,
        message: input.attendeesWereNotified
          ? 'Cancelled the event. Attendees were notified.'
          : 'Cancelled the event.',
      };
    } catch (error) {
      const recovered = recoverCalendarGraphError({
        error,
        logger: this.logger,
        userProfileId: userProfileIdString,
        mailbox,
        callerEmail: userProfile.email,
        calendarId: input.eventRef.calendarId,
        operation: 'cancel_event',
        notFoundMessage:
          'That event was not found. Search again and pass eventRef without changing it.',
        invalidMessage: 'Graph rejected the cancellation. Only the organizer can cancel a meeting.',
        deniedDelegatedMessage: `Could not cancel an event on mailbox ${mailbox}.`,
      });
      if (recovered === undefined) {
        throw error;
      }
      return recovered;
    }
  }
}
