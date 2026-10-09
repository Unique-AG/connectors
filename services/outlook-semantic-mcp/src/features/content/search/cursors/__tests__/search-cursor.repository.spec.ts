import { describe, expect, it } from 'vitest';
import { createMockDrizzleDatabase } from '~/__mocks__';
import type { DrizzleDatabase } from '~/db';
import { SearchBackend } from '../../search-results.types';
import { SearchCursorRepository } from '../search-cursor.repository';

const USER_PROFILE_ID = 'user_profile_01kqcg8m7teh6sh8tehd2k0byb';

const graphPayload = {
  backend: SearchBackend.MsGraph,
  kqlQuery: 'subject:test',
  mailbox: 'own@example.com',
  isDelegated: false,
  url: '/users/own@example.com/messages?$skip=25',
  delivered: 25,
} as const;

const createRepository = () => {
  const db = createMockDrizzleDatabase();
  return { db, repository: new SearchCursorRepository(db as unknown as DrizzleDatabase) };
};

describe(SearchCursorRepository.name, () => {
  it('inserts one row per payload for the user and returns the ids in order', async () => {
    const { db, repository } = createRepository();

    const ids = await repository.create(USER_PROFILE_ID, [
      graphPayload,
      { ...graphPayload, delivered: 50 },
    ]);

    const insertedRows = db.insert.mock.results[0]?.value.values.mock.calls[0]?.[0];
    expect(ids).toHaveLength(2);
    expect(ids.every((id) => id.startsWith('search_cursor_'))).toBe(true);
    expect(insertedRows).toEqual([
      { id: ids[0], userProfileId: USER_PROFILE_ID, payload: graphPayload },
      { id: ids[1], userProfileId: USER_PROFILE_ID, payload: { ...graphPayload, delivered: 50 } },
    ]);
  });

  it('does not touch the database when there is nothing to store', async () => {
    const { db, repository } = createRepository();

    expect(await repository.create(USER_PROFILE_ID, [])).toEqual([]);
    expect(db.insert).not.toHaveBeenCalled();
  });

  it('returns stored payloads by id and drops rows that no longer match the schema', async () => {
    const { db, repository } = createRepository();
    db.__nextSelectRows = [
      { id: 'search_cursor_valid', payload: graphPayload },
      { id: 'search_cursor_invalid', payload: { backend: 'Unknown' } },
    ];

    const cursors = await repository.findForUser(USER_PROFILE_ID, [
      'search_cursor_valid',
      'search_cursor_invalid',
    ]);

    expect(Array.from(cursors.keys())).toEqual(['search_cursor_valid']);
    expect(cursors.get('search_cursor_valid')).toEqual(graphPayload);
  });
});
