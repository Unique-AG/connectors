import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { filter, flatMap, isNonNullish, map, pipe, sortBy, uniqueBy } from 'remeda';
import { z } from 'zod';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { nameSimilarity } from '~/utils/name-similarity-score';

const MsGraphPeopleResponseSchema = z.object({
  value: z
    .array(
      z.object({
        displayName: z.string().optional(),
        scoredEmailAddresses: z.array(z.object({ address: z.string().optional() })).optional(),
      }),
    )
    .optional(),
});

const MsGraphInboxMessagesResponseSchema = z.object({
  value: z
    .array(
      z.object({
        from: z
          .object({
            emailAddress: z
              .object({
                name: z.string().optional(),
                address: z.string().optional(),
              })
              .optional(),
          })
          .optional(),
      }),
    )
    .optional(),
});

export interface Contact {
  name: string;
  email: string;
  source: 'people_api' | 'inbox';
}

export const LookupContactsResultSchema = z.object({
  contacts: z
    .array(
      z.object({
        name: z.string().describe('Display name of the contact.'),
        email: z.string().describe('Email address of the contact.'),
        source: z
          .enum(['people_api', 'inbox'])
          .describe(
            'Where the contact was found: "people_api" means the Microsoft People API returned it ' +
              '(typically colleagues and frequent contacts); "inbox" means it was extracted from recent incoming mail.',
          ),
        similarityScore: z
          .number()
          .describe(
            "Jaro-Winkler similarity between the search query and this contact's display name. " +
              'Ranges from 0 (no similarity) to 1 (exact match). ' +
              'The list is sorted by this score descending — prefer contacts with a higher score when the query is ambiguous.',
          ),
      }),
    )
    .describe(
      'Matched contacts sorted by name similarity descending, deduplicated by email address.',
    ),
  message: z.string().optional().describe('Present when a data source could not be reached.'),
});

export type LookupContactsResult = z.infer<typeof LookupContactsResultSchema>;

@Injectable()
export class LookupContactsQuery {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly graphClientFactory: GraphClientFactory) {}

  @Span()
  public async run(userProfileId: UserProfileTypeID, name: string): Promise<LookupContactsResult> {
    const userProfileIdString = userProfileId.toString();
    const client = this.graphClientFactory.createClientForUser(userProfileIdString);

    const peopleContacts = await this.fetchFromPeopleApi(userProfileIdString, client, name);
    if (!peopleContacts) {
      return { contacts: [], message: 'Could not reach Microsoft Graph' };
    }
    const inboxContacts = await this.fetchFromInbox(userProfileIdString, client);
    if (!inboxContacts) {
      return { contacts: [], message: 'Could not reach Microsoft Graph' };
    }

    // Contacts scoring below this threshold are excluded from results.
    // 0.75 reliably passes partial name queries (e.g. "Smith" → "John Smith" ≈ 0.76)
    // while rejecting unrelated names (e.g. "Alice" → "John Smith" ≈ 0.40).
    const SimilarityThreshold = 0.75;

    // We return the full ranked list to the LLM so it can choose the best match
    // rather than guessing on the caller's behalf.
    const contacts = pipe(
      [...peopleContacts, ...inboxContacts],
      map(({ email, ...contact }) => ({
        ...contact,
        email: email.toLocaleLowerCase(),
        similarityScore: nameSimilarity(name, contact.name),
      })),
      // peopleContacts are already filtered server-side by the People API $search.
      // inboxContacts are unfiltered — apply the similarity threshold to remove unrelated senders.
      filter(
        ({ source, similarityScore }) =>
          source === 'people_api' || similarityScore >= SimilarityThreshold,
      ),
      uniqueBy(({ email }) => email),
      sortBy([({ similarityScore }) => similarityScore, 'desc']),
    );
    console.log(contacts);

    return { contacts, message: `Contacts fetch succesfully` };
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
          // The People API requires the $search value to be wrapped in double quotes.
          // Any literal quotes in the input are stripped to prevent query injection.
          $search: `"${name.replace(/"/g, '')}"`,
          $top: 50,
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

    const { value: items = [] } = MsGraphPeopleResponseSchema.parse(raw);
    return pipe(
      items,
      filter(({ displayName }) => isNonNullish(displayName)),
      flatMap(({ displayName, scoredEmailAddresses }) =>
        pipe(
          scoredEmailAddresses ?? [],
          map(({ address }) => address),
          filter(isNonNullish),
          map((address) => ({
            name: displayName as string,
            email: address,
            source: 'people_api' as const,
          })),
        ),
      ),
    );
  }

  private async fetchFromInbox(
    userProfileIdString: string,
    client: ReturnType<GraphClientFactory['createClientForUser']>,
  ): Promise<Contact[] | null> {
    let raw: unknown;
    try {
      raw = await client
        .api('/me/messages')
        .query({
          $select: 'from',
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

    const { value: items = [] } = MsGraphInboxMessagesResponseSchema.parse(raw);
    return pipe(
      items,
      map((message) => {
        const senderName = message.from?.emailAddress?.name;
        const senderEmail = message.from?.emailAddress?.address;
        if (!senderName || !senderEmail) {
          return null;
        }
        return { name: senderName, email: senderEmail, source: 'inbox' as const };
      }),
      filter(isNonNullish),
    );
  }
}
