import { Client } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { UserProfile } from '~/db';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
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

const CALENDAR_SELECT = 'id,name,owner,canEdit,canShare,canViewPrivateItems,isDefaultCalendar';

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
    private readonly graphClientFactory: GraphClientFactory,
    private readonly msGraphClientResolver: MsGraphClientResolver,
    private readonly getUserProfileQuery: GetUserProfileQuery,
  ) {}

  @Span()
  public async run(userProfileId: UserProfileTypeID): Promise<ListCalendarsQueryOutput> {
    const userProfile = await this.getUserProfileQuery.run(userProfileId);

    try {
      const calendars =
        userProfile.source === 'shared-mailbox'
          ? await this.listForSharedMailbox(userProfile)
          : await this.listForOauthUser(userProfile);

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
        return {
          success: false,
          message: error.message,
        };
      }
      throw error;
    }
  }

  private async listForOauthUser(userProfile: NonNullishProps<UserProfile, 'email'>) {
    const client = this.graphClientFactory.createClientForUser(userProfile.id);
    return this.fetchCalendars(client, '/me/calendars', userProfile.email);
  }

  private async listForSharedMailbox(userProfile: NonNullishProps<UserProfile, 'email'>) {
    return this.msGraphClientResolver.run({
      userProfile,
      sharedMailboxConfig: { throwIfNoDelegates: true },
      fn: async ({ client }) =>
        this.fetchCalendars(client, `/users/${userProfile.email}/calendars`, userProfile.email),
    });
  }

  private async fetchCalendars(client: Client, path: string, callerEmail: string) {
    const calendars = [];
    let nextPath: string | undefined = path;
    let isFirst = true;

    while (nextPath) {
      try {
        const request = client.api(nextPath);
        const raw = isFirst ? await request.select(CALENDAR_SELECT).get() : await request.get();
        isFirst = false;
        const parsed = GraphCalendarCollectionSchema.safeParse(raw);
        if (!parsed.success) {
          this.logger.warn({ msg: 'Unexpected /calendars response shape', err: parsed.error });
          break;
        }
        for (const item of parsed.data.value) {
          calendars.push(classifyCalendar(item, callerEmail));
        }
        nextPath = parsed.data['@odata.nextLink'];
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
