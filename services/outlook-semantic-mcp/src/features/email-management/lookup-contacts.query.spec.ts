import { describe, expect, it } from 'vitest';
import { LookupContactsQuery } from './lookup-contacts.query';

// biome-ignore lint/suspicious/noExplicitAny: test stub
const USER_PROFILE_ID = { toString: () => 'user-1' } as any;

function makeClient(opts: {
  people?: unknown;
  peopleError?: Error;
  inbox?: unknown;
  inboxError?: Error;
}) {
  // biome-ignore lint/suspicious/noExplicitAny: mock does not need full type fidelity
  const client: any = {
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
  return client;
}

function makeFactory(opts: Parameters<typeof makeClient>[0]) {
  const client = makeClient(opts);
  return {
    // biome-ignore lint/suspicious/noExplicitAny: mock factory does not need full type fidelity
    createClientForUser: (_id: string): any => client,
  };
}

describe('LookupContactsQuery.run', () => {
  it('merges contacts from both sources when both return results', async () => {
    const query = new LookupContactsQuery(
      makeFactory({
        people: {
          value: [
            { displayName: 'Alice Smith', scoredEmailAddresses: [{ address: 'alice@example.com' }] },
          ],
        },
        inbox: {
          value: [{ from: { emailAddress: { name: 'Bob Jones', address: 'bob@example.com' } } }],
        },
      }) as any,
    );

    const result = await query.run(USER_PROFILE_ID, 'bob');

    expect(result).toEqual({
      contacts: [
        { name: 'Alice Smith', email: 'alice@example.com', source: 'people_api' },
        { name: 'Bob Jones', email: 'bob@example.com', source: 'inbox' },
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
      }) as any,
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
            { displayName: 'Alice Smith', scoredEmailAddresses: [{ address: 'alice@example.com' }] },
          ],
        },
        inboxError: new Error('Inbox unavailable'),
      }) as any,
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
      }) as any,
    );

    const result = await query.run(USER_PROFILE_ID, 'alice');

    expect(result).toEqual({ contacts: [], message: 'Could not reach Microsoft Graph' });
  });

  it('deduplicates contacts by email (case-insensitive) with people_api winning on conflict', async () => {
    const query = new LookupContactsQuery(
      makeFactory({
        people: {
          value: [
            { displayName: 'Alice Smith', scoredEmailAddresses: [{ address: 'Alice@Example.com' }] },
          ],
        },
        inbox: {
          value: [
            { from: { emailAddress: { name: 'Alice from Inbox', address: 'alice@example.com' } } },
          ],
        },
      }) as any,
    );

    const result = await query.run(USER_PROFILE_ID, 'alice');

    expect(result).toEqual({
      contacts: [{ name: 'Alice Smith', email: 'Alice@Example.com', source: 'people_api' }],
    });
  });
});
