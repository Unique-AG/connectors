import { Client } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { UserProfile } from '~/db';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import {
  AllDelegatesFailedError,
  MsGraphClientResolver,
  NoDelegatesFoundError,
} from '~/msgraph/ms-graph-client-resolver.service';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { NonNullishProps } from '~/utils/non-nullish-props';
import { CalendarRefSchema, GraphCalendarCollectionSchema } from './calendar.schemas';
import {
  CalendarConsentRequiredError,
  isInsufficientCalendarScopeError,
} from './calendar-graph-errors';
import { classifyCalendar } from './classify-calendar';

const CALENDAR_SELECT =
  'id,name,owner,canEdit,canShare,canViewPrivateItems,isDefaultCalendar,isTallyingResponses';

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

@Injectable()
export class ListCalendarsQuery {
  private readonly logger = new Logger(ListCalendarsQuery.name);

  public constructor(
    private readonly msGraphClientResolver: MsGraphClientResolver,
    private readonly getUserProfileQuery: GetUserProfileQuery,
  ) {}

  @Span()
  public async run(userProfileId: UserProfileTypeID): Promise<ListCalendarsQueryOutput> {
    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    const path =
      userProfile.source === 'shared-mailbox'
        ? `/users/${userProfile.email}/calendars`
        : '/me/calendars';

    try {
      const calendars = await this.msGraphClientResolver.run({
        userProfile,
        sharedMailboxConfig: { throwIfNoDelegates: true },
        fn: ({ client }) => this.fetchCalendars(client, path, userProfile.email),
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

  private async fetchCalendars(
    client: Client,
    path: string,
    callerEmail: NonNullishProps<UserProfile, 'email'>['email'],
  ) {
    const calendars = [];
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
          calendars.push(classifyCalendar(item, callerEmail));
        }
        nextPath = parsed['@odata.nextLink'];
      } catch (error) {
        if (isInsufficientCalendarScopeError(error)) {
          throw new CalendarConsentRequiredError();
        }
        throw error;
      }
    }

    return calendars;
  }
}
