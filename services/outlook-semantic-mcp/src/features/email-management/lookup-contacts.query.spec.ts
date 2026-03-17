import { describe, expect, it } from 'vitest';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { LookupContactsQuery } from './lookup-contacts.query';

const USER_PROFILE_ID = { toString: () => 'user-1' } as unknown as UserProfileTypeID;

interface MockQueryChain {
  get: () => Promise<unknown>;
}

interface MockClient {
  api: (path: string) => { query: () => MockQueryChain };
}

function makeClient(opts: {
  people?: unknown;
  peopleError?: Error;
  inbox?: unknown;
  inboxError?: Error;
}): MockClient {
  return {
    api: (path: string) => ({
      query: () => ({
        get: async () => {
          if (path === '/me/people') {
            if (opts.peopleError) {
              throw opts.peopleError;
            }
            return opts.people ?? { value: [] };
          }
          if (opts.inboxError) {
            throw opts.inboxError;
          }
          return opts.inbox ?? { value: [] };
        },
      }),
    }),
  };
}

function makeFactory(opts: Parameters<typeof makeClient>[0]) {
  const client = makeClient(opts);
  return {
    createClientForUser: (_id: string): MockClient => client,
  } as unknown as GraphClientFactory;
}

describe('LookupContactsQuery.run', () => {
  it('merges contacts from both sources when both return results', async () => {
    const query = new LookupContactsQuery(
      makeFactory({
        people: {
          value: [
            {
              displayName: 'Alice Smith',
              scoredEmailAddresses: [{ address: 'alice@example.com' }],
            },
          ],
        },
        inbox: {
          value: [
            { from: { emailAddress: { name: 'Alice Brown', address: 'alice.brown@example.com' } } },
          ],
        },
      }),
    );

    const result = await query.run(USER_PROFILE_ID, 'alice');

    expect(result).toEqual({
      contacts: [
        { name: 'Alice Smith', email: 'alice@example.com', source: 'people_api' },
        { name: 'Alice Brown', email: 'alice.brown@example.com', source: 'inbox' },
      ],
    });
  });

  it('falls back to inbox results only when People API fails', async () => {
    const query = new LookupContactsQuery(
      makeFactory({
        peopleError: new Error('People API unavailable'),
        inbox: {
          value: [{ from: { emailAddress: { name: 'Bob Jones', address: 'bob@example.com' } } }],
        },
      }),
    );

    const result = await query.run(USER_PROFILE_ID, 'bob');

    expect(result).toEqual({
      contacts: [{ name: 'Bob Jones', email: 'bob@example.com', source: 'inbox' }],
    });
  });

  it('falls back to People API results only when inbox fetch fails', async () => {
    const query = new LookupContactsQuery(
      makeFactory({
        people: {
          value: [
            {
              displayName: 'Alice Smith',
              scoredEmailAddresses: [{ address: 'alice@example.com' }],
            },
          ],
        },
        inboxError: new Error('Inbox unavailable'),
      }),
    );

    const result = await query.run(USER_PROFILE_ID, 'alice');

    expect(result).toEqual({
      contacts: [{ name: 'Alice Smith', email: 'alice@example.com', source: 'people_api' }],
    });
  });

  it('returns empty contacts with error message when both sources fail', async () => {
    const query = new LookupContactsQuery(
      makeFactory({
        peopleError: new Error('People API unavailable'),
        inboxError: new Error('Inbox unavailable'),
      }),
    );

    const result = await query.run(USER_PROFILE_ID, 'alice');

    expect(result).toEqual({ contacts: [], message: 'Could not reach Microsoft Graph' });
  });

  it('deduplicates contacts by email (case-insensitive) with people_api winning on conflict', async () => {
    const query = new LookupContactsQuery(
      makeFactory({
        people: {
          value: [
            {
              displayName: 'Alice Smith',
              scoredEmailAddresses: [{ address: 'Alice@Example.com' }],
            },
          ],
        },
        inbox: {
          value: [
            { from: { emailAddress: { name: 'Alice from Inbox', address: 'alice@example.com' } } },
          ],
        },
      }),
    );

    const result = await query.run(USER_PROFILE_ID, 'alice');

    expect(result).toEqual({
      contacts: [{ name: 'Alice Smith', email: 'Alice@Example.com', source: 'people_api' }],
    });
  });
});
