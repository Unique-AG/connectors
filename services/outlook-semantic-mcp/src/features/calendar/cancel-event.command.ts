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
import { eventCancelPath } from './utils/calendar-graph-path';
import { SmtpAddressSchema } from './utils/smtp-address.schema';

export interface CancelEventCommandInput {
  eventRef: EventRef;
  targetEventId: string;
  comment?: string;
  notifyAttendees: boolean;
}

export interface CancelEventCommandOutput {
  success: boolean;
  message: string;
  consentRequired?: boolean;
}

@Injectable()
export class CancelEventCommand {
  private readonly logger = new Logger(CancelEventCommand.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getUserProfileQuery: GetUserProfileQuery,
  ) {}

  @Span()
  public async run(
    userProfileId: UserProfileTypeID,
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
      this.logger.log({ msg: 'cancel_event', mailbox });
      return {
        success: true,
        message: input.notifyAttendees
          ? 'Cancelled the event. Attendees were notified.'
          : 'Cancelled the event.',
      };
    } catch (error) {
      if (error instanceof GraphError && error.statusCode === 404) {
        return {
          success: false,
          message: 'That event was not found. Search again and pass eventRef without changing it.',
        };
      }
      if (error instanceof GraphError && error.statusCode === 400) {
        return {
          success: false,
          message: 'Graph rejected the cancellation. Only the organizer can cancel a meeting.',
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
          message: `Could not cancel an event on mailbox ${mailbox}.`,
        };
      }
      throw error;
    }
  }
}
