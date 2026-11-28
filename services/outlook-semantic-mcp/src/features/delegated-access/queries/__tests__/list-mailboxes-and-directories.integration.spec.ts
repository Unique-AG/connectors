import assert from 'node:assert';
import path from 'node:path';
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from '@testcontainers/postgresql';
import { drizzle } from 'drizzle-orm/node-postgres';
import { migrate } from 'drizzle-orm/node-postgres/migrator';
import type { Pool } from 'pg';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { loadFeaturesConfig } from '~/config';
import type { DrizzleDatabase } from '~/db';
import * as schema from '~/db/schema';
import { createPostgresPool, stopPostgres } from '../../../../__mocks__/stop-postgres';
import { ListMailboxesAndDirectoriesQuery } from '../list-mailboxes-and-directories.query';

const CONTAINER_STARTUP_TIMEOUT_MS = 120_000;

describe(ListMailboxesAndDirectoriesQuery.name, () => {
  let container: StartedPostgreSqlContainer;
  let pool: Pool;
  let db: DrizzleDatabase;
  let ownId: string;

  beforeAll(async () => {
    container = await new PostgreSqlContainer('postgres:17-alpine').start();
    pool = createPostgresPool(container.getConnectionUri());
    db = drizzle({ client: pool, casing: 'snake_case', schema });
    await migrate(db, { migrationsFolder: path.resolve(__dirname, '../../../../../drizzle') });
  }, CONTAINER_STARTUP_TIMEOUT_MS);

  afterAll(async () => {
    await stopPostgres(pool, container);
  });

  beforeEach(async () => {
    await db.delete(schema.userProfiles);
    const [own, owner] = await db
      .insert(schema.userProfiles)
      .values([
        {
          provider: 'microsoft',
          providerUserId: 'provider-ada',
          username: 'ada',
          email: 'ada@contoso.example',
          displayName: 'Ada',
        },
        {
          provider: 'microsoft',
          providerUserId: 'provider-grace',
          username: 'grace',
          email: 'grace@contoso.example',
          displayName: 'Grace',
        },
      ])
      .returning();
    assert.ok(own && owner);
    ownId = own.id;
    await db.insert(schema.directories).values([
      {
        userProfileId: own.id,
        internalType: 'Inbox',
        providerDirectoryId: 'ada-inbox',
        displayName: 'Inbox',
      },
      {
        userProfileId: owner.id,
        internalType: 'Inbox',
        providerDirectoryId: 'grace-inbox',
        displayName: 'Inbox',
      },
    ]);
    await db
      .insert(schema.delegatedAccessAccounts)
      .values({ delegateUserId: own.id, ownerUserId: owner.id, hasFullDelegatedAccess: true });
  });

  const listFor = (scan: string) =>
    new ListMailboxesAndDirectoriesQuery(
      db,
      loadFeaturesConfig({
        MCP_BACKEND: 'microsoft_graph',
        DELEGATED_ACCESS_SCAN: scan,
        MCP_TOOLS: JSON.stringify(['list_mailboxes_and_directories']),
      }),
    ).run(ownId);

  it('lists the mailboxes shared with the user when shared mailboxes are on', async () => {
    const mailboxes = await listFor('full_access_only');

    expect(mailboxes.map(({ email, isOwn }) => ({ email, isOwn }))).toEqual([
      { email: 'ada@contoso.example', isOwn: true },
      { email: 'grace@contoso.example', isOwn: false },
    ]);
  });

  it('lists only the own mailbox with DELEGATED_ACCESS_SCAN=disabled', async () => {
    const mailboxes = await listFor('disabled');

    expect(mailboxes.map(({ email, isOwn }) => ({ email, isOwn }))).toEqual([
      { email: 'ada@contoso.example', isOwn: true },
    ]);
  });
});
