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
import {
  EVENT_RESPONSES,
  type EventResponse,
  eventResponsePath,
} from './utils/calendar-graph-path';
import {
  calendarLogUser,
  calendarTraceAttrs,
  calendarUserProfileId,
  recoverCalendarGraphError,
} from './utils/calendar-observability';

export interface RespondToInviteCommandInput {
  eventRef: EventRef;
  response: EventResponse;
  comment?: string;
}

export interface RespondToInviteCommandOutput {
  success: boolean;
  message: string;
  response?: EventResponse;
  consentRequired?: boolean;
  errorType?: CalendarMetricErrorType;
}

@Injectable()
export class RespondToInviteCommand {
  private readonly logger = new Logger(RespondToInviteCommand.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getUserProfileQuery: GetUserProfileQuery,
    private readonly calendarMetrics: CalendarMetricsService,
  ) {}

  @Span()
  public async run(
    userProfileId: UserProfileTypeID,
    input: RespondToInviteCommandInput,
  ): Promise<RespondToInviteCommandOutput> {
    const userProfileIdString = calendarUserProfileId(userProfileId);
    this.logger.debug({
      userProfileId: userProfileIdString,
      calendarId: input.eventRef.calendarId,
      response: input.response,
      msg: 'respond_to_invite started',
    });
    return this.calendarMetrics.measureOperation({ operation: 'respond_to_invite' }, () =>
      this.respond(userProfileId, userProfileIdString, input),
    );
  }

  private async respond(
    userProfileId: UserProfileTypeID,
    userProfileIdString: string,
    input: RespondToInviteCommandInput,
  ): Promise<RespondToInviteCommandOutput> {
    assert.ok(
      (EVENT_RESPONSES as readonly string[]).includes(input.response),
      'response must already be accept, tentativelyAccept, or decline',
    );
    assert.ok(input.eventRef.eventId.length > 0, 'eventRef.eventId must already be set');
    assert.ok(input.eventRef.calendarId.length > 0, 'eventRef.calendarId must already be set');

    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    calendarTraceAttrs({
      userProfileId: userProfileIdString,
      userProfileEmail: userProfile.email,
      calendarId: input.eventRef.calendarId,
      operation: 'respond_to_invite',
    });
    const client = this.graphClientFactory.createClientForUser(userProfile.id);
    const path = eventResponsePath({
      calendarId: input.eventRef.calendarId,
      eventId: input.eventRef.eventId,
      response: input.response,
    });
    const comment = input.comment?.trim();

    try {
      await client
        .api(path)
        .header('Prefer', 'IdType="ImmutableId"')
        .post({
          sendResponse: true,
          ...(comment !== undefined && comment !== '' ? { comment } : {}),
        });
      this.logger.log({
        ...calendarLogUser(userProfileIdString, userProfile.email),
        calendarId: input.eventRef.calendarId,
        response: input.response,
        msg: 'respond_to_invite',
      });
      return {
        success: true,
        message: responseSentMessage(input.response),
        response: input.response,
      };
    } catch (error) {
      return recoverCalendarGraphError({
        error,
        logger: this.logger,
        userProfileId: userProfileIdString,
        userProfileEmail: userProfile.email,
        calendarId: input.eventRef.calendarId,
        operation: 'respond_to_invite',
        notFoundMessage:
          'That event was not found. Search again and pass eventRef without changing it.',
      });
    }
  }
}

function responseSentMessage(response: EventResponse): string {
  if (response === 'accept') {
    return 'Accepted the invitation. The organizer was notified.';
  }
  if (response === 'tentativelyAccept') {
    return 'Tentatively accepted the invitation. The organizer was notified.';
  }
  return 'Declined the invitation. The organizer was notified.';
}
