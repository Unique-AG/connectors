import assert from 'node:assert';
import { Client } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { GetFullAccessMailboxesQuery } from '~/features/delegated-access/queries/get-full-access-mailboxes.query';
import { isDelegatedAccessNotAvailableError } from '~/features/delegated-access/utils/is-delegated-access-not-available-error';
import {
  type CalendarMetricErrorType,
  CalendarMetricsService,
} from '~/features/metrics/calendar-metrics.service';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { obfuscateEmail } from '~/utils/obfuscate-email';
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
  listNotes?: string[];
  consentRequired?: boolean;
  errorType?: CalendarMetricErrorType;
}

@Injectable()
export class ListCalendarsQuery {
  private readonly logger = new Logger(ListCalendarsQuery.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getUserProfileQuery: GetUserProfileQuery,
    private readonly getFullAccessMailboxesQuery: GetFullAccessMailboxesQuery,
    private readonly calendarMetrics: CalendarMetricsService,
  ) {}

  @Span()
  public async run(userProfileId: UserProfileTypeID): Promise<ListCalendarsQueryOutput> {
    const userProfileIdString = calendarUserProfileId(userProfileId);
    this.logger.debug({ userProfileId: userProfileIdString, msg: 'list_calendars started' });
    calendarTraceAttrs({ userProfileId: userProfileIdString, operation: 'list_calendars' });
    return this.calendarMetrics.measureOperation({ operation: 'list_calendars' }, async () => {
      const userProfile = await this.getUserProfileQuery.run(userProfileId);
      const client = this.graphClientFactory.createClientForUser(userProfile.id);

      try {
        const { calendars, notes } = await this.fetchOauthCalendars({
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
          ...(notes.length > 0 ? { listNotes: notes } : {}),
        };
      } catch (error) {
        if (error instanceof CalendarConsentRequiredError) {
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
            errorType: 'consent' as const,
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
  }): Promise<{ calendars: CalendarRef[]; notes: string[] }> {
    const own = await this.fetchCalendars({
      client: input.client,
      path: calendarCollectionPath(input.callerEmail),
      mailboxEmail: input.callerEmail,
      callerEmail: input.callerEmail,
      userProfileId: input.userProfileId,
      consentOnDenied: true,
    });
    // Exchange Full Access is a mailbox-wide grant that includes the calendar, so the delegated-access
    // table is a legitimate source of owner mailboxes to ask Graph about — and only that. Every
    // candidate below is still probed, so a stale row cannot conjure access that does not exist.
    // It is empty by configuration when discovery is off, which the note distinguishes.
    const { scanDisabled, ownerEmails: fullAccessMailboxes } =
      await this.getFullAccessMailboxesQuery.run(input.userId);
    const ownerEmails = fullAccessMailboxes.filter(
      (email) => email !== input.callerEmail.toLowerCase(),
    );
    if (ownerEmails.length === 0) {
      this.logger.log({
        userProfileId: input.userProfileId,
        mailbox: obfuscateEmail(input.callerEmail),
        calendarCount: own.length,
        delegatedMailboxCount: 0,
        delegatedScanDisabled: scanDisabled,
        msg: 'list_calendars',
      });
      return {
        calendars: rankCalendars(own),
        notes: scanDisabled
          ? [
              'Calendars of mailboxes you have Full Access to are not listed because delegated-access discovery is turned off on this deployment. Calendars shared with you directly are listed.',
            ]
          : [],
      };
    }

    using limit = calendarGraphLimit(input.userId);
    const delegatedLists = await Promise.all(
      ownerEmails.map((ownerEmail) =>
        limit(async (): Promise<{ calendars: CalendarRef[] } | { skippedMailbox: string }> => {
          try {
            return {
              calendars: await this.fetchCalendars({
                client: input.client,
                path: calendarCollectionPath(ownerEmail),
                mailboxEmail: ownerEmail,
                callerEmail: input.callerEmail,
                userProfileId: input.userProfileId,
              }),
            };
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
              return { skippedMailbox: ownerEmail };
            }
            throw error;
          }
        }),
      ),
    );

    const notes: string[] = [];
    const reachedOwners = new Set<string>();
    const delegated: CalendarRef[] = [];
    for (const [index, list] of delegatedLists.entries()) {
      const ownerEmail = ownerEmails[index];
      assert.ok(ownerEmail);
      if ('skippedMailbox' in list) {
        notes.push(`Could not list calendars for ${list.skippedMailbox}.`);
        continue;
      }
      if (list.calendars.length === 0) {
        continue;
      }
      reachedOwners.add(ownerEmail);
      delegated.push(...list.calendars);
    }

    const fromMe = own.filter((calendar) => {
      const owner = calendar.ownerEmail?.toLowerCase();
      return owner === undefined || owner === null || !reachedOwners.has(owner);
    });
    const calendars = rankCalendars([...fromMe, ...delegated]);
    this.logger.log({
      userProfileId: input.userProfileId,
      mailbox: obfuscateEmail(input.callerEmail),
      calendarCount: calendars.length,
      delegatedMailboxCount: ownerEmails.length,
      msg: 'list_calendars',
    });
    return { calendars, notes };
  }

  @Span()
  private async fetchCalendars(input: {
    client: Client;
    path: string;
    mailboxEmail: string;
    callerEmail: string;
    userProfileId: string;
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
              mailboxEmail: input.mailboxEmail,
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

/** Primary calendars first so holiday and extra calendars do not hide the meeting calendars. */
function rankCalendars(calendars: CalendarRef[]): CalendarRef[] {
  return [...calendars].sort((left, right) => calendarRank(left) - calendarRank(right));
}

function calendarRank(calendar: CalendarRef): number {
  if (calendar.isDefaultCalendar) {
    return calendar.isOwn ? 0 : 1;
  }
  return calendar.isOwn ? 2 : 3;
}
