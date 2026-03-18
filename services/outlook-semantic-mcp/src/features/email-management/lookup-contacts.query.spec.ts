import { describe, expect, it } from 'vitest';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { LookupContactsQuery } from './lookup-contacts.query';

const USER_PROFILE_ID = { toString: () => 'user-1' } as unknown as UserProfileTypeID;

// Matches a contact's non-score fields without coupling tests to exact float values.
function withScore(contact: { name: string; email: string; source: 'people_api' | 'inbox' }) {
  return expect.objectContaining({ ...contact, similarityScore: expect.any(Number) });
}

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
  describe('result shape', () => {
    it('attaches a numeric similarityScore to every contact', async () => {
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
        }),
      );

      const result = await query.run(USER_PROFILE_ID, 'alice');

      expect(result.contacts[0]).toMatchObject({ similarityScore: expect.any(Number) });
    });

    it('always includes a message field on success', async () => {
      const query = new LookupContactsQuery(makeFactory({}));

      const result = await query.run(USER_PROFILE_ID, 'alice');

      expect(result.message).toBeDefined();
    });

    it('lowercases email addresses in the output', async () => {
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
        }),
      );

      const result = await query.run(USER_PROFILE_ID, 'alice');

      expect(result.contacts[0].email).toBe('alice@example.com');
    });
  });

  describe('error handling', () => {
    it('returns an error and no contacts when the People API fails — no fallback to inbox', async () => {
      const query = new LookupContactsQuery(
        makeFactory({
          peopleError: new Error('People API unavailable'),
          inbox: {
            value: [{ from: { emailAddress: { name: 'Bob Jones', address: 'bob@example.com' } } }],
          },
        }),
      );

      const result = await query.run(USER_PROFILE_ID, 'bob');

      expect(result).toEqual({ contacts: [], message: 'Could not reach Microsoft Graph' });
    });

    it('returns an error and no contacts when the inbox fetch fails — no fallback to People API', async () => {
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

      expect(result).toEqual({ contacts: [], message: 'Could not reach Microsoft Graph' });
    });

    it('returns an error when both sources fail', async () => {
      const query = new LookupContactsQuery(
        makeFactory({
          peopleError: new Error('People API unavailable'),
          inboxError: new Error('Inbox unavailable'),
        }),
      );

      const result = await query.run(USER_PROFILE_ID, 'alice');

      expect(result).toEqual({ contacts: [], message: 'Could not reach Microsoft Graph' });
    });
  });

  describe('merging and deduplication', () => {
    it('merges contacts from both sources', async () => {
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
              {
                from: {
                  emailAddress: { name: 'Alice Brown', address: 'alice.brown@example.com' },
                },
              },
            ],
          },
        }),
      );

      const result = await query.run(USER_PROFILE_ID, 'alice');

      expect(result.contacts).toEqual(
        expect.arrayContaining([
          withScore({ name: 'Alice Smith', email: 'alice@example.com', source: 'people_api' }),
          withScore({ name: 'Alice Brown', email: 'alice.brown@example.com', source: 'inbox' }),
        ]),
      );
    });

    it('deduplicates by email address keeping the highest-scoring entry', async () => {
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
              {
                from: { emailAddress: { name: 'Alice from Inbox', address: 'alice@example.com' } },
              },
            ],
          },
        }),
      );

      const result = await query.run(USER_PROFILE_ID, 'alice');

      expect(result.contacts).toHaveLength(1);
      expect(result.contacts[0]).toMatchObject({ source: 'people_api' });
    });

    it('deduplication is case-insensitive on the email address', async () => {
      const query = new LookupContactsQuery(
        makeFactory({
          people: {
            value: [
              {
                displayName: 'Alice Smith',
                scoredEmailAddresses: [{ address: 'ALICE@EXAMPLE.COM' }],
              },
            ],
          },
          inbox: {
            value: [
              {
                from: { emailAddress: { name: 'Alice from Inbox', address: 'alice@example.com' } },
              },
            ],
          },
        }),
      );

      const result = await query.run(USER_PROFILE_ID, 'alice');

      expect(result.contacts).toHaveLength(1);
    });
  });

  describe('similarity filtering and sorting', () => {
    it('filters out inbox contacts with a name that does not match the query', async () => {
      const query = new LookupContactsQuery(
        makeFactory({
          inbox: {
            value: [
              {
                from: {
                  emailAddress: { name: 'Alice Brown', address: 'alice.brown@example.com' },
                },
              },
              // "Xavier Unrelated" has very low Jaro-Winkler similarity to "alice"
              {
                from: { emailAddress: { name: 'Xavier Unrelated', address: 'xavier@example.com' } },
              },
            ],
          },
        }),
      );

      const result = await query.run(USER_PROFILE_ID, 'alice');

      expect(result.contacts.map((c) => c.name)).toContain('Alice Brown');
      expect(result.contacts.map((c) => c.name)).not.toContain('Xavier Unrelated');
    });

    it('passes through all people_api contacts regardless of similarity — the People API already filtered server-side', async () => {
      const query = new LookupContactsQuery(
        makeFactory({
          people: {
            value: [
              {
                displayName: 'Xavier Unrelated',
                scoredEmailAddresses: [{ address: 'xavier@example.com' }],
              },
            ],
          },
        }),
      );

      const result = await query.run(USER_PROFILE_ID, 'alice');

      expect(result.contacts.map((c) => c.name)).toContain('Xavier Unrelated');
    });

    it('sorts contacts by similarity score descending', async () => {
      // "John Smith" scores 1.0 against "john smith" (exact full-name match).
      // "John Anderson" scores lower because the second token does not match.
      const query = new LookupContactsQuery(
        makeFactory({
          people: {
            value: [
              {
                displayName: 'John Anderson',
                scoredEmailAddresses: [{ address: 'john.a@example.com' }],
              },
              {
                displayName: 'John Smith',
                scoredEmailAddresses: [{ address: 'john.s@example.com' }],
              },
            ],
          },
        }),
      );

      const result = await query.run(USER_PROFILE_ID, 'john smith');

      expect(result.contacts[0].name).toBe('John Smith');
      expect(result.contacts[0].similarityScore).toBeGreaterThanOrEqual(
        result.contacts[1].similarityScore,
      );
    });
  });
});
