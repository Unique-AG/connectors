import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { filter, flatMap, pipe, uniqueBy } from 'remeda';
import { z } from 'zod';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';

const PeopleResponseSchema = z.object({
  value: z
    .array(
      z.object({
        displayName: z.string().optional(),
        scoredEmailAddresses: z.array(z.object({ address: z.string().optional() })).optional(),
      }),
    )
    .optional(),
});

const InboxEmailAddressSchema = z.object({
  name: z.string().optional(),
  address: z.string().optional(),
});

const InboxMessagesResponseSchema = z.object({
  value: z
    .array(
      z.object({ from: z.object({ emailAddress: InboxEmailAddressSchema.optional() }).optional() }),
    )
    .optional(),
});

export interface Contact {
  name: string;
  email: string;
  source: 'people_api' | 'inbox';
}

export interface LookupContactsResult {
  contacts: Contact[];
  message?: string;
}

@Injectable()
export class LookupContactsQuery {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly graphClientFactory: GraphClientFactory) {}

  @Span()
  public async run(userProfileId: UserProfileTypeID, name: string): Promise<LookupContactsResult> {
    const userProfileIdString = userProfileId.toString();
    const client = this.graphClientFactory.createClientForUser(userProfileIdString);

    let [peopleContacts, inboxContacts] = await Promise.all([
      this.fetchFromPeopleApi(userProfileIdString, client, name),
      this.fetchFromInbox(userProfileIdString, client, name),
    ]);

    if (peopleContacts === null && inboxContacts === null) {
      return { contacts: [], message: 'Could not reach Microsoft Graph' };
    }
    peopleContacts ??= [];
    inboxContacts ??= [];

    return {
      contacts: uniqueBy([...peopleContacts, ...inboxContacts], (item) => item.email.toLowerCase()),
    };
  }

  private async fetchFromPeopleApi(
    userProfileIdString: string,
    client: ReturnType<GraphClientFactory['createClientForUser']>,
    name: string,
  ): Promise<Contact[] | null> {
    let raw: unknown;
    try {
      raw = await client
        .api('/me/people')
        .query({
          $search: name.replace(/"/g, ''),
          $top: 25,
          $select: 'displayName,scoredEmailAddresses',
        })
        .get();
    } catch (err) {
      this.logger.error({
        userProfileId: userProfileIdString,
        msg: 'Failed to fetch contacts from People API',
        err,
      });
      return null;
    }

    const { value: items = [] } = PeopleResponseSchema.parse(raw);
    return pipe(
      items,
      flatMap((person) => {
        const email = person.scoredEmailAddresses?.[0]?.address;
        return person.displayName && email
          ? [{ name: person.displayName, email, source: 'people_api' as const }]
          : [];
      }),
    );
  }

  private async fetchFromInbox(
    userProfileIdString: string,
    client: ReturnType<GraphClientFactory['createClientForUser']>,
    name: string,
  ): Promise<Contact[] | null> {
    let raw: unknown;
    try {
      raw = await client
        .api('/me/messages')
        .query({
          $select: 'from/emailAddress/name,from/emailAddress/address',
          $top: 100,
          $orderby: 'receivedDateTime desc',
        })
        .get();
    } catch (err) {
      this.logger.error({
        userProfileId: userProfileIdString,
        msg: 'Failed to fetch contacts from inbox',
        err,
      });
      return null;
    }

    const { value: items = [] } = InboxMessagesResponseSchema.parse(raw);
    const queryWords = name.toLowerCase().split(/\s+/);
    return pipe(
      items,
      filter((message) => {
        const fromName = message.from?.emailAddress?.name;
        if (!fromName) {
          return false;
        }
        const nameWords = fromName.toLowerCase().split(/\s+/);
        return queryWords.every((qw) => nameWords.some((nw) => nw.startsWith(qw)));
      }),
      flatMap((message) => {
        const fromName = message.from?.emailAddress?.name;
        const fromEmail = message.from?.emailAddress?.address;
        return fromName && fromEmail
          ? [{ name: fromName, email: fromEmail, source: 'inbox' as const }]
          : [];
      }),
    );
  }
}
