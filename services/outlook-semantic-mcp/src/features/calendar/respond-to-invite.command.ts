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
import {
  EVENT_RESPONSES,
  type EventResponse,
  eventResponsePath,
} from './utils/calendar-graph-path';
import {
  calendarTraceAttrs,
  calendarUserProfileId,
  classifyCalendarGraphError,
  logCalendarRecovered,
} from './utils/calendar-observability';
import { SmtpAddressSchema } from './utils/smtp-address.schema';

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
      mailbox: obfuscateEmail(input.eventRef.mailbox),
      calendarId: input.eventRef.calendarId,
      response: input.response,
      msg: 'respond_to_invite started',
    });
    calendarTraceAttrs({
      userProfileId: userProfileIdString,
      mailbox: input.eventRef.mailbox,
      calendarId: input.eventRef.calendarId,
      operation: 'respond_to_invite',
    });
    return this.calendarMetrics.measureOperation({ operation: 'respond_to_invite' }, (fail) =>
      this.respond(userProfileId, userProfileIdString, input, fail),
    );
  }

  private async respond(
    userProfileId: UserProfileTypeID,
    userProfileIdString: string,
    input: RespondToInviteCommandInput,
    fail: (errorType: CalendarMetricErrorType) => void,
  ): Promise<RespondToInviteCommandOutput> {
    assert.ok(
      (EVENT_RESPONSES as readonly string[]).includes(input.response),
      'response must already be accept, tentativelyAccept, or decline',
    );
    assert.ok(
      SmtpAddressSchema.safeParse(input.eventRef.mailbox).success,
      'eventRef.mailbox must already be an SMTP address',
    );
    assert.ok(input.eventRef.eventId.length > 0, 'eventRef.eventId must already be set');
    assert.ok(input.eventRef.calendarId.length > 0, 'eventRef.calendarId must already be set');

    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    const mailbox = input.eventRef.mailbox;
    const client = this.graphClientFactory.createClientForUser(userProfile.id);
    const path = eventResponsePath({
      mailboxEmail: mailbox,
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
        userProfileId: userProfileIdString,
        mailbox: obfuscateEmail(mailbox),
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
      const recovered = classifyCalendarGraphError({
        error,
        mailbox,
        callerEmail: userProfile.email,
        notFoundMessage:
          'That event was not found. Search again and pass eventRef without changing it.',
        deniedDelegatedMessage: `Could not respond to an invite on mailbox ${mailbox}.`,
      });
      if (recovered === undefined) {
        throw error;
      }
      fail(recovered.outcome);
      logCalendarRecovered(this.logger, {
        userProfileId: userProfileIdString,
        mailbox,
        calendarId: input.eventRef.calendarId,
        outcome: recovered.outcome,
        msg: `respond_to_invite ${recovered.outcome}`,
        err: error,
      });
      return {
        success: false,
        message: recovered.message,
        ...(recovered.consentRequired === true ? { consentRequired: true } : {}),
      };
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
