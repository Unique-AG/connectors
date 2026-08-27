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
import type { EventRef } from './calendar.schemas';
import { eventCancelPath } from './utils/calendar-graph-path';
import {
  calendarLogUser,
  calendarTraceAttrs,
  calendarUserProfileId,
  recoverCalendarGraphError,
} from './utils/calendar-observability';

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
      calendarId: input.eventRef.calendarId,
      msg: 'cancel_event started',
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
    assert.ok(input.eventRef.calendarId.length > 0, 'eventRef.calendarId must already be set');
    assert.ok(input.targetEventId.length > 0, 'targetEventId must already be set');

    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    calendarTraceAttrs({
      userProfileId: userProfileIdString,
      userProfileEmail: userProfile.email,
      calendarId: input.eventRef.calendarId,
      operation: 'cancel_event',
    });
    const client = this.graphClientFactory.createClientForUser(userProfile.id);
    const path = eventCancelPath({
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
        ...calendarLogUser(userProfileIdString, userProfile.email),
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
      return recoverCalendarGraphError({
        error,
        logger: this.logger,
        userProfileId: userProfileIdString,
        userProfileEmail: userProfile.email,
        calendarId: input.eventRef.calendarId,
        operation: 'cancel_event',
        notFoundMessage:
          'That event was not found. Search again and pass eventRef without changing it.',
        invalidMessage: 'Graph rejected the cancellation. Only the organizer can cancel a meeting.',
      });
    }
  }
}
