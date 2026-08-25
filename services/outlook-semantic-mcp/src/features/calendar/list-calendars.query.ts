import assert from 'node:assert';
import { Client } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { GetFullDelegatedAccessQuery } from '~/features/delegated-access/queries/get-full-delegated-access.query';
import { isDelegatedAccessNotAvailableError } from '~/features/delegated-access/utils/is-delegated-access-not-available-error';
import { CalendarMetricsService } from '~/features/metrics/calendar-metrics.service';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { CalendarRef, GraphCalendarCollectionSchema } from './calendar.schemas';
import {
  CalendarConsentRequiredError,
  isCalendarPermissionDeniedError,
} from './utils/calendar-graph-errors';
import { calendarGraphLimit } from './utils/calendar-graph-limit';
import { calendarCollectionPath } from './utils/calendar-graph-path';
import {
  calendarTraceAttrs,
  calendarUserProfileId,
  logCalendarRecovered,
} from './utils/calendar-observability';
import { mapGraphCalendarToCalendarRef } from './utils/map-graph-calendar-to-calendar-ref';

const CALENDAR_SELECT =
  'id,name,owner,canEdit,canShare,canViewPrivateItems,isDefaultCalendar,isTallyingResponses';

export interface ListCalendarsQueryOutput {
  success: boolean;
  message: string;
  calendars?: CalendarRef[];
  consentRequired?: boolean;
}

@Injectable()
export class ListCalendarsQuery {
  private readonly logger = new Logger(ListCalendarsQuery.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getUserProfileQuery: GetUserProfileQuery,
    private readonly getFullDelegatedAccessQuery: GetFullDelegatedAccessQuery,
    private readonly calendarMetrics: CalendarMetricsService,
  ) {}

  @Span()
  public async run(userProfileId: UserProfileTypeID): Promise<ListCalendarsQueryOutput> {
    const userProfileIdString = calendarUserProfileId(userProfileId);
    this.logger.debug({ userProfileId: userProfileIdString, msg: 'list_calendars started' });
    calendarTraceAttrs({ userProfileId: userProfileIdString, operation: 'list_calendars' });
    return this.calendarMetrics.measureOperation({ operation: 'list_calendars' }, async (fail) => {
      const userProfile = await this.getUserProfileQuery.run(userProfileId);
      const client = this.graphClientFactory.createClientForUser(userProfile.id);

      try {
        const calendars = await this.fetchOauthCalendars({
          client,
          userId: userProfile.id,
          userProfileId: userProfileIdString,
          callerEmail: userProfile.email,
        });

        return {
          success: true,
          message:
            calendars.length === 0
              ? 'No calendars were returned.'
              : `Found ${calendars.length} calendar${calendars.length === 1 ? '' : 's'}.`,
          calendars,
        };
      } catch (error) {
        if (error instanceof CalendarConsentRequiredError) {
          fail('consent');
          logCalendarRecovered(this.logger, {
            userProfileId: userProfileIdString,
            mailbox: userProfile.email,
            outcome: 'consent',
            msg: 'list_calendars consent required',
            err: error,
          });
          return {
            success: false,
            message: error.message,
            consentRequired: true,
          };
        }
        throw error;
      }
    });
  }

  private async fetchOauthCalendars(input: {
    client: Client;
    userId: string;
    userProfileId: string;
    callerEmail: string;
  }): Promise<CalendarRef[]> {
    const own = await this.fetchCalendars({
      client: input.client,
      path: calendarCollectionPath(input.callerEmail),
      mailboxEmail: input.callerEmail,
      callerEmail: input.callerEmail,
      userProfileId: input.userProfileId,
      consentOnDenied: true,
    });
    const accesses = await this.getFullDelegatedAccessQuery.run(input.userId);
    const ownerEmails = [
      ...new Set(
        accesses
          .map((access) => access.ownerUserEmail.toLowerCase())
          .filter((email) => email !== input.callerEmail.toLowerCase()),
      ),
    ];
    if (ownerEmails.length === 0) {
      this.logger.log({
        userProfileId: input.userProfileId,
        mailbox: input.callerEmail,
        calendarCount: own.length,
        delegatedMailboxCount: 0,
        msg: 'list_calendars',
      });
      return own;
    }

    using limit = calendarGraphLimit(input.userId);
    const delegatedLists = await Promise.all(
      ownerEmails.map((ownerEmail) =>
        limit(async () => {
          try {
            return await this.fetchCalendars({
              client: input.client,
              path: calendarCollectionPath(ownerEmail),
              mailboxEmail: ownerEmail,
              callerEmail: input.callerEmail,
              userProfileId: input.userProfileId,
              accessPathOverride: 'ownerMailbox',
            });
          } catch (error) {
            if (isDelegatedAccessNotAvailableError(error)) {
              logCalendarRecovered(this.logger, {
                userProfileId: input.userProfileId,
                mailbox: input.callerEmail,
                ownerEmail,
                outcome: 'delegated_skipped',
                msg: 'Skipped delegated mailbox calendars',
                err: error,
              });
              return null;
            }
            throw error;
          }
        }),
      ),
    );

    const reachedOwners = new Set<string>();
    const delegated: CalendarRef[] = [];
    for (const [index, list] of delegatedLists.entries()) {
      if (list === null || list.length === 0) {
        continue;
      }
      const ownerEmail = ownerEmails[index];
      assert.ok(ownerEmail);
      reachedOwners.add(ownerEmail);
      delegated.push(...list);
    }

    const fromMe = own.filter((calendar) => {
      const owner = calendar.ownerEmail?.toLowerCase();
      return owner === undefined || owner === null || !reachedOwners.has(owner);
    });
    const calendars = [...fromMe, ...delegated];
    this.logger.log({
      userProfileId: input.userProfileId,
      mailbox: input.callerEmail,
      calendarCount: calendars.length,
      delegatedMailboxCount: ownerEmails.length,
      msg: 'list_calendars',
    });
    return calendars;
  }

  @Span()
  private async fetchCalendars(input: {
    client: Client;
    path: string;
    mailboxEmail: string;
    callerEmail: string;
    userProfileId: string;
    accessPathOverride?: CalendarRef['accessPath'];
    consentOnDenied?: boolean;
  }): Promise<CalendarRef[]> {
    calendarTraceAttrs({
      userProfileId: input.userProfileId,
      mailbox: input.mailboxEmail,
      operation: 'list_calendars.fetch',
    });
    const calendars: CalendarRef[] = [];
    let nextPath: string | undefined = input.path;
    let isFirst = true;

    while (nextPath) {
      try {
        const request = input.client.api(nextPath);
        const raw = isFirst
          ? await request.select(CALENDAR_SELECT).top(100).get()
          : await request.get();
        isFirst = false;
        const parsed = GraphCalendarCollectionSchema.parse(raw);
        for (const item of parsed.value) {
          calendars.push(
            mapGraphCalendarToCalendarRef({
              calendar: item,
              callerEmail: input.callerEmail,
              accessPathOverride: input.accessPathOverride,
            }),
          );
        }
        nextPath = parsed['@odata.nextLink'];
      } catch (error) {
        if (input.consentOnDenied && isCalendarPermissionDeniedError(error)) {
          throw new CalendarConsentRequiredError();
        }
        throw error;
      }
    }

    return calendars;
  }
}
