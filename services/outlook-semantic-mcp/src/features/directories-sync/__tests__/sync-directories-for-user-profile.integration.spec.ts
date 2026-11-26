/** biome-ignore-all lint/suspicious/noExplicitAny: Graph resolver, config and Unique client stand-ins */
import assert from 'node:assert';
import path from 'node:path';
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from '@testcontainers/postgresql';
import { eq } from 'drizzle-orm';
import { drizzle } from 'drizzle-orm/node-postgres';
import { migrate } from 'drizzle-orm/node-postgres/migrator';
import type { Pool } from 'pg';
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { McpBackendType } from '~/config';
import type { DrizzleDatabase } from '~/db';
import * as schema from '~/db/schema';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { createPostgresPool, stopPostgres } from '../../../__mocks__/stop-postgres';
import { IsInboxDeletingQuery } from '../../delete-inbox/is-inbox-deleting.query';
import { GetUserProfileQuery } from '../../user-utils/get-user-profile.query';
import { CreateRootScopeCommand } from '../create-root-scope.command';
import type { GraphOutlookDirectory } from '../microsoft-graph.dtos';
import { SyncDirectoriesForUserProfileCommand } from '../sync-directories-for-user-profile.command';
import { UpsertDirectoryCommand } from '../upsert-directory.command';

const CONTAINER_STARTUP_TIMEOUT_MS = 120_000;

const graphFolder = (id: string, displayName: string): GraphOutlookDirectory => ({
  id,
  displayName,
  childFolderCount: 0,
  totalItemCount: 0,
  unreadItemCount: 0,
  parentFolderId: 'msgfolderroot',
});

describe('SyncDirectoriesForUserProfileCommand against Postgres', () => {
  let container: StartedPostgreSqlContainer;
  let pool: Pool;
  let db: DrizzleDatabase;
  let uniqueApi: {
    scopes: Record<
      'getByExternalId' | 'createFromPaths' | 'updateExternalId',
      ReturnType<typeof vi.fn>
    >;
    files: Record<'getIdsByScopeAndMetadataKey' | 'deleteByIds', ReturnType<typeof vi.fn>>;
  };
  let userProfileId: string;

  beforeAll(async () => {
    container = await new PostgreSqlContainer('postgres:17-alpine').start();
    pool = createPostgresPool(container.getConnectionUri());
    db = drizzle({ client: pool, casing: 'snake_case', schema });
    await migrate(db, { migrationsFolder: path.resolve(__dirname, '../../../../drizzle') });
  }, CONTAINER_STARTUP_TIMEOUT_MS);

  afterAll(async () => {
    await stopPostgres(pool, container);
  });

  beforeEach(async () => {
    await db.delete(schema.userProfiles);

    const [user] = await db
      .insert(schema.userProfiles)
      .values({
        provider: 'microsoft',
        providerUserId: 'provider-user-1',
        username: 'ada',
        email: 'ada@contoso.example',
        source: 'oauth',
        accessToken: 'access-token',
        refreshToken: 'refresh-token',
      })
      .returning();
    assert.ok(user);
    userProfileId = user.id;
    await db.insert(schema.directoriesSync).values({ userProfileId });
    await db.insert(schema.directories).values([
      {
        userProfileId,
        internalType: 'Inbox',
        providerDirectoryId: 'inbox-id',
        displayName: 'Inbox',
      },
      {
        userProfileId,
        internalType: 'User Defined Directory',
        providerDirectoryId: 'removed-in-outlook-id',
        displayName: 'Old projects',
      },
    ]);

    uniqueApi = {
      scopes: {
        getByExternalId: vi.fn().mockResolvedValue({ id: 'scope-1' }),
        createFromPaths: vi.fn(),
        updateExternalId: vi.fn(),
      },
      files: {
        getIdsByScopeAndMetadataKey: vi.fn().mockResolvedValue(['content-1']),
        deleteByIds: vi.fn(),
      },
    };
  });

  function commandFor(mode: McpBackendType): SyncDirectoriesForUserProfileCommand {
    return new SyncDirectoriesForUserProfileCommand(
      db,
      uniqueApi as any,
      { run: vi.fn().mockResolvedValue([graphFolder('projects-id', 'Projects')]) } as any,
      new GetUserProfileQuery(db),
      { run: vi.fn() } as any,
      new CreateRootScopeCommand(uniqueApi as any),
      new UpsertDirectoryCommand(db),
      new IsInboxDeletingQuery(db),
      { run: ({ fn }: { fn: (args: { client: object }) => unknown }) => fn({ client: {} }) } as any,
      { mode } as any,
    );
  }

  async function folderIds(): Promise<string[]> {
    const rows = await db
      .select({ id: schema.directories.providerDirectoryId })
      .from(schema.directories)
      .where(eq(schema.directories.userProfileId, userProfileId));
    return rows.map((row) => row.id).sort();
  }

  const uniqueCalls = () =>
    [...Object.values(uniqueApi.scopes), ...Object.values(uniqueApi.files)].flatMap(
      (fn) => fn.mock.calls,
    );

  describe('in microsoft_graph mode', () => {
    it('syncs the folder table and makes no call on the Unique API client', async () => {
      await commandFor(McpBackendType.MicrosoftGraph).run(
        convertUserProfileIdToTypeId(userProfileId),
      );

      expect(await folderIds()).toEqual(['inbox-id', 'projects-id']);
      const [sync] = await db
        .select({ ranAt: schema.directoriesSync.lastDirectorySyncRanAt })
        .from(schema.directoriesSync)
        .where(eq(schema.directoriesSync.userProfileId, userProfileId));
      expect(sync?.ranAt).toBeInstanceOf(Date);
      expect(uniqueCalls()).toEqual([]);
    });
  });

  describe('in Unique mode', () => {
    it('keeps the root scope and deletes the removed folder files in Unique', async () => {
      await commandFor(McpBackendType.MicrosoftGraphAndUniqueApi).run(
        convertUserProfileIdToTypeId(userProfileId),
      );

      expect(await folderIds()).toEqual(['inbox-id', 'projects-id']);
      expect(uniqueApi.scopes.getByExternalId).toHaveBeenCalled();
      expect(uniqueApi.files.getIdsByScopeAndMetadataKey).toHaveBeenCalledWith(
        'scope-1',
        'parentFolderId',
        'removed-in-outlook-id',
      );
      expect(uniqueApi.files.deleteByIds).toHaveBeenCalledWith(['content-1']);
    });
  });
});
