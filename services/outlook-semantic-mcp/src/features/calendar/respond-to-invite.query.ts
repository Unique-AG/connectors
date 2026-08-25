import assert from 'node:assert';
import { GraphError } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import type { EventRef } from './calendar.schemas';
import {
  CalendarConsentRequiredError,
  isCalendarPermissionDeniedError,
} from './utils/calendar-graph-errors';
import {
  EVENT_RESPONSES,
  type EventResponse,
  eventResponsePath,
} from './utils/calendar-graph-path';
import { SmtpAddressSchema } from './utils/smtp-address.schema';

export interface RespondToInviteQueryInput {
  eventRef: EventRef;
  response: EventResponse;
  comment?: string;
}

export interface RespondToInviteQueryOutput {
  success: boolean;
  message: string;
  response?: EventResponse;
  consentRequired?: boolean;
}

@Injectable()
export class RespondToInviteQuery {
  private readonly logger = new Logger(RespondToInviteQuery.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getUserProfileQuery: GetUserProfileQuery,
  ) {}

  @Span()
  public async run(
    userProfileId: UserProfileTypeID,
    input: RespondToInviteQueryInput,
  ): Promise<RespondToInviteQueryOutput> {
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
        msg: 'respond_to_invite',
        response: input.response,
        mailbox,
      });
      return {
        success: true,
        message: responseSentMessage(input.response),
        response: input.response,
      };
    } catch (error) {
      if (error instanceof GraphError && error.statusCode === 404) {
        return {
          success: false,
          message: 'That event was not found. Search again and pass eventRef without changing it.',
        };
      }
      if (isCalendarPermissionDeniedError(error)) {
        if (mailbox.toLowerCase() === userProfile.email.toLowerCase()) {
          return {
            success: false,
            message: new CalendarConsentRequiredError().message,
            consentRequired: true,
          };
        }
        return {
          success: false,
          message: `Could not respond to an invite on mailbox ${mailbox}.`,
        };
      }
      throw error;
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
