import assert from 'node:assert';
import { Client } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import pLimit from 'p-limit';
import * as z from 'zod';
import { UserProfile } from '~/db';
import { GetFullDelegatedAccessQuery } from '~/features/delegated-access/queries/get-full-delegated-access.query';
import { isDelegatedAccessNotAvailableError } from '~/features/delegated-access/utils/is-delegated-access-not-available-error';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import {
  AllDelegatesFailedError,
  MsGraphClientResolver,
  NoDelegatesFoundError,
} from '~/msgraph/ms-graph-client-resolver.service';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { NonNullishProps } from '~/utils/non-nullish-props';
import { CalendarRef, CalendarRefSchema, GraphCalendarCollectionSchema } from './calendar.schemas';
import {
  CalendarConsentRequiredError,
  isCalendarPermissionDeniedError,
} from './calendar-graph-errors';
import { classifyCalendar } from './classify-calendar';

const CALENDAR_SELECT =
  'id,name,owner,canEdit,canShare,canViewPrivateItems,isDefaultCalendar,isTallyingResponses';
const DELEGATED_CALENDAR_CONCURRENCY = 5;

export const ListCalendarsQueryOutputSchema = z.object({
  success: z
    .boolean()
    .describe('True when the calendar list was retrieved. False when Graph access failed.'),
  message: z.string().describe('Human-readable summary of the outcome.'),
  calendars: z
    .array(CalendarRefSchema)
    .optional()
    .describe('Calendars the signed-in user can access, including own, shared, and delegated.'),
  consentRequired: z
    .boolean()
    .optional()
    .describe(
      'True when calendar scopes have not been granted yet. The user must reconnect Outlook before calendar tools will work.',
    ),
});

export type ListCalendarsQueryOutput = z.infer<typeof ListCalendarsQueryOutputSchema>;

interface FetchCalendarsOptions {
  accessPathOverride?: CalendarRef['accessPath'];
  consentOnDenied?: boolean;
}

@Injectable()
export class ListCalendarsQuery {
  private readonly logger = new Logger(ListCalendarsQuery.name);

  public constructor(
    private readonly msGraphClientResolver: MsGraphClientResolver,
    private readonly getUserProfileQuery: GetUserProfileQuery,
    private readonly getFullDelegatedAccessQuery: GetFullDelegatedAccessQuery,
  ) {}

  @Span()
  public async run(userProfileId: UserProfileTypeID): Promise<ListCalendarsQueryOutput> {
    const userProfile = await this.getUserProfileQuery.run(userProfileId);

    try {
      const calendars = await this.msGraphClientResolver.run({
        userProfile,
        sharedMailboxConfig: { throwIfNoDelegates: true },
        fn: ({ client }) =>
          userProfile.source === 'shared-mailbox'
            ? this.fetchCalendars(
                client,
                `/users/${userProfile.email}/calendars`,
                userProfile.email,
              )
            : this.fetchOauthCalendars(client, userProfile),
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
        return {
          success: false,
          message: error.message,
          consentRequired: true,
        };
      }
      if (error instanceof NoDelegatesFoundError || error instanceof AllDelegatesFailedError) {
        this.logger.warn({ msg: 'Shared mailbox calendar list failed', err: error });
        return {
          success: false,
          message:
            'Could not reach this shared mailbox through a connected Outlook account. Ask a mailbox owner to reconnect.',
        };
      }
      throw error;
    }
  }

  private async fetchOauthCalendars(
    client: Client,
    userProfile: NonNullishProps<UserProfile, 'email'>,
  ): Promise<CalendarRef[]> {
    const own = await this.fetchCalendars(client, '/me/calendars', userProfile.email, {
      consentOnDenied: true,
    });
    const accesses = await this.getFullDelegatedAccessQuery.run(userProfile.id);
    const ownerEmails = [
      ...new Set(
        accesses
          .map((access) => access.ownerUserEmail.toLowerCase())
          .filter((email) => email !== userProfile.email.toLowerCase()),
      ),
    ];
    if (ownerEmails.length === 0) {
      return own;
    }

    const limit = pLimit(DELEGATED_CALENDAR_CONCURRENCY);
    const delegatedLists = await Promise.all(
      ownerEmails.map((ownerEmail) =>
        limit(async () => {
          try {
            return await this.fetchCalendars(
              client,
              `/users/${ownerEmail}/calendars`,
              userProfile.email,
              { accessPathOverride: 'ownerMailbox' },
            );
          } catch (error) {
            if (isDelegatedAccessNotAvailableError(error)) {
              this.logger.warn({
                msg: 'Skipped delegated mailbox calendars',
                ownerEmail,
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
    return [...fromMe, ...delegated];
  }

  private async fetchCalendars(
    client: Client,
    path: string,
    callerEmail: NonNullishProps<UserProfile, 'email'>['email'],
    options: FetchCalendarsOptions = {},
  ): Promise<CalendarRef[]> {
    const calendars: CalendarRef[] = [];
    let nextPath: string | undefined = path;
    let isFirst = true;

    while (nextPath) {
      try {
        const request = client.api(nextPath);
        const raw = isFirst
          ? await request.select(CALENDAR_SELECT).top(100).get()
          : await request.get();
        isFirst = false;
        const parsed = GraphCalendarCollectionSchema.parse(raw);
        for (const item of parsed.value) {
          calendars.push(classifyCalendar(item, callerEmail, options.accessPathOverride));
        }
        nextPath = parsed['@odata.nextLink'];
      } catch (error) {
        if (options.consentOnDenied && isCalendarPermissionDeniedError(error)) {
          throw new CalendarConsentRequiredError();
        }
        throw error;
      }
    }

    return calendars;
  }
}
