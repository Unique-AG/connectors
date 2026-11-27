/** biome-ignore-all lint/suspicious/noExplicitAny: Graph client, resolver and query stand-ins */
import assert from 'node:assert';
import path from 'node:path';
import { type McpAuthenticatedRequest, UpstreamCredentialRevokedError } from '@unique-ag/mcp-oauth';
import type { Context } from '@unique-ag/mcp-server-module';
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from '@testcontainers/postgresql';
import { eq } from 'drizzle-orm';
import { drizzle } from 'drizzle-orm/node-postgres';
import { migrate } from 'drizzle-orm/node-postgres/migrator';
import type { Pool } from 'pg';
import { afterAll, beforeAll, beforeEach, describe, expect, it, type Mock, vi } from 'vitest';
import { type FeaturesConfig, loadFeaturesConfig } from '~/config';
import type { DrizzleDatabase } from '~/db';
import * as schema from '~/db/schema';
import { ListMailboxesAndDirectoriesQuery } from '~/features/delegated-access/queries/list-mailboxes-and-directories.query';
import { IsInboxDeletingQuery } from '~/features/delete-inbox/is-inbox-deleting.query';
import type { GraphOutlookDirectory } from '~/features/directories-sync/microsoft-graph.dtos';
import {
  ON_DEMAND_DIRECTORY_SYNC_MAX_AGE_MS,
  ON_DEMAND_DIRECTORY_SYNC_RETRY_AFTER_MS,
  RefreshStaleDirectoriesCommand,
} from '~/features/directories-sync/refresh-stale-directories.command';
import { SyncDirectoriesCommand } from '~/features/directories-sync/sync-directories.command';
import { SyncDirectoriesForUserProfileCommand } from '~/features/directories-sync/sync-directories-for-user-profile.command';
import { ListMailboxesAndDirectoriesTool } from '~/features/directories-sync/tools/list-mailboxes-and-directories.tool';
import { UpsertDirectoryCommand } from '~/features/directories-sync/upsert-directory.command';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { createPostgresPool, stopPostgres } from '../../../../__mocks__/stop-postgres';
import { SensitivityFilter } from '../../sensitivity-filter';
import { BuildMsGraphKqlBatchRequestsQuery } from '../build-ms-graph-kql-batch-requests.query';
import { SearchCursorRepository } from '../cursors/search-cursor.repository';
import { MsGraphKqlSearchEmailsQuery } from '../ms-graph-kql-search-emails.query';
import { SearchEmailsQuery } from '../search-emails.query';

const CONTAINER_STARTUP_TIMEOUT_MS = 120_000;
const HOUR_MS = 60 * 60 * 1000;

const graphFolder = (id: string, displayName: string): GraphOutlookDirectory => ({
  id,
  displayName,
  childFolderCount: 0,
  totalItemCount: 0,
  unreadItemCount: 0,
  parentFolderId: 'msgfolderroot',
});

const INBOX = graphFolder('inbox-id', 'Inbox');
// Created in Outlook after the user signed in, so not in the folder table yet.
const PROJECTS = graphFolder('projects-id', 'Projects');

const featuresWith = (directorySyncMode: string): FeaturesConfig =>
  loadFeaturesConfig({
    MCP_BACKEND: 'microsoft_graph',
    MCP_TOOLS: JSON.stringify(['search_emails', 'list_mailboxes_and_directories']),
    DELEGATED_ACCESS_SCAN: 'disabled',
    DIRECTORY_SYNC_MODE: directorySyncMode,
  });

describe('Folder cache with DIRECTORY_SYNC_MODE against Postgres', () => {
  let container: StartedPostgreSqlContainer;
  let pool: Pool;
  let db: DrizzleDatabase;
  let userProfileId: string;
  // Folder delta reads and $batch search requests sent to Microsoft Graph.
  let folderDeltaReads: Mock;
  let searchBatches: Mock;

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
    await db.insert(schema.directories).values({
      userProfileId,
      internalType: 'Inbox',
      providerDirectoryId: INBOX.id,
      displayName: INBOX.displayName,
    });

    folderDeltaReads = vi.fn().mockResolvedValue({
      value: [PROJECTS],
      '@odata.deltaLink': 'https://graph.microsoft.com/v1.0/me/mailFolders/delta?$deltatoken=2',
    });
    searchBatches = vi.fn().mockImplementation(({ requests }: { requests: { id: string }[] }) =>
      Promise.resolve({
        responses: requests.map(({ id }) => ({ id, status: 200, body: { value: [] } })),
      }),
    );
  });

  const lastSyncedHoursAgo = (hours: number) =>
    db.insert(schema.directoriesSync).values({
      userProfileId,
      lastDeltaSyncRanAt: new Date(Date.now() - hours * HOUR_MS),
    });

  function syncDirectoriesCommand(features: FeaturesConfig): SyncDirectoriesCommand {
    const graph = {
      api: () => ({ query: () => ({ get: folderDeltaReads }), get: folderDeltaReads }),
    };
    const resolver = {
      run: ({ fn }: { fn: (args: object) => unknown }) =>
        fn({ client: graph, clientUserProfileId: userProfileId }),
    };
    const getUserProfileQuery = new GetUserProfileQuery(db);
    return new SyncDirectoriesCommand(
      db,
      resolver as any,
      getUserProfileQuery,
      new SyncDirectoriesForUserProfileCommand(
        db,
        {} as any,
        { run: vi.fn().mockResolvedValue([INBOX, PROJECTS]) } as any,
        getUserProfileQuery,
        { run: vi.fn() } as any,
        {} as any,
        new UpsertDirectoryCommand(db),
        new IsInboxDeletingQuery(db),
        resolver as any,
        features,
      ),
    );
  }

  function searchEmailsQuery(features: FeaturesConfig): SearchEmailsQuery {
    const getUserProfileQuery = new GetUserProfileQuery(db);
    const graphSearch = new MsGraphKqlSearchEmailsQuery(
      { createClientForUser: () => ({ api: () => ({ post: searchBatches }) }) } as any,
      getUserProfileQuery,
      { run: vi.fn().mockResolvedValue(new Map()) } as any,
      new BuildMsGraphKqlBatchRequestsQuery(
        new ListMailboxesAndDirectoriesQuery(db, features),
        getUserProfileQuery,
      ),
      { run: vi.fn() } as any,
      new SensitivityFilter(features),
    );
    return new SearchEmailsQuery(
      { run: vi.fn() } as any,
      graphSearch,
      { run: vi.fn().mockResolvedValue(undefined) } as any,
      new SearchCursorRepository(db),
      new RefreshStaleDirectoriesCommand(db, syncDirectoriesCommand(features), features),
      features,
    );
  }

  const searchProjectsFolder = (features: FeaturesConfig) =>
    searchEmailsQuery(features).run(convertUserProfileIdToTypeId(userProfileId), {
      msGraphKeywordSearchQueries: [{ kqlQuery: 'budget', directories: [PROJECTS.id] }],
    });

  const searchedUrls = (): string[] =>
    searchBatches.mock.calls.flatMap(([{ requests }]) =>
      requests.map(({ url }: { url: string }) => url),
    );

  describe('on_demand', () => {
    const features = featuresWith('on_demand');

    it('syncs before a folder-filtered search when the last sync is older than the max age, and resolves a folder created after sign-in', async () => {
      await lastSyncedHoursAgo(ON_DEMAND_DIRECTORY_SYNC_MAX_AGE_MS / HOUR_MS + 1);

      const output = await searchProjectsFolder(features);

      expect(folderDeltaReads).toHaveBeenCalled();
      expect(searchedUrls()).toEqual([
        expect.stringContaining(`/users/ada@contoso.example/mailFolders/${PROJECTS.id}/messages`),
      ]);
      expect(output.searchSummary ?? '').not.toContain(PROJECTS.id);
      const [sync] = await db
        .select({ ranAt: schema.directoriesSync.lastDeltaSyncRanAt })
        .from(schema.directoriesSync)
        .where(eq(schema.directoriesSync.userProfileId, userProfileId));
      expect(Date.now() - (sync?.ranAt?.getTime() ?? 0)).toBeLessThan(HOUR_MS);
    });

    it('syncs before a folder-filtered search when the user was never synced', async () => {
      await searchProjectsFolder(features);

      expect(folderDeltaReads).toHaveBeenCalled();
      expect(searchedUrls()).toEqual([expect.stringContaining(`/mailFolders/${PROJECTS.id}/`)]);
    });

    it('searches the cached folders without syncing when the last sync is newer than the max age', async () => {
      await lastSyncedHoursAgo(1);

      const output = await searchProjectsFolder(features);

      expect(folderDeltaReads).not.toHaveBeenCalled();
      expect(searchedUrls()).toEqual([]);
      expect(output.searchSummary).toContain(PROJECTS.id);
    });

    it('searches the cached folders when the folder sync fails', async () => {
      await lastSyncedHoursAgo(ON_DEMAND_DIRECTORY_SYNC_MAX_AGE_MS / HOUR_MS + 1);
      folderDeltaReads.mockRejectedValue(new Error('Graph is unavailable'));

      const output = await searchEmailsQuery(features).run(
        convertUserProfileIdToTypeId(userProfileId),
        {
          msGraphKeywordSearchQueries: [
            { kqlQuery: 'budget', directories: [INBOX.id, PROJECTS.id] },
          ],
        },
      );

      expect(searchedUrls()).toEqual([expect.stringContaining(`/mailFolders/${INBOX.id}/`)]);
      expect(output.searchSummary).toContain(PROJECTS.id);
    });

    it('shares one folder sync between concurrent searches of the same user', async () => {
      await lastSyncedHoursAgo(ON_DEMAND_DIRECTORY_SYNC_MAX_AGE_MS / HOUR_MS + 1);
      const query = searchEmailsQuery(features);
      const search = () =>
        query.run(convertUserProfileIdToTypeId(userProfileId), {
          msGraphKeywordSearchQueries: [{ kqlQuery: 'budget', directories: [PROJECTS.id] }],
        });

      await Promise.all([search(), search(), search()]);

      expect(folderDeltaReads).toHaveBeenCalledTimes(1);
      expect(searchedUrls()).toHaveLength(3);
    });

    it('does not retry a failed folder sync on the next search', async () => {
      await lastSyncedHoursAgo(ON_DEMAND_DIRECTORY_SYNC_MAX_AGE_MS / HOUR_MS + 1);
      folderDeltaReads.mockRejectedValue(new Error('Graph is unavailable'));
      const query = searchEmailsQuery(features);
      const search = () =>
        query.run(convertUserProfileIdToTypeId(userProfileId), {
          msGraphKeywordSearchQueries: [{ kqlQuery: 'budget', directories: [INBOX.id] }],
        });

      await search();
      const readsAfterFailure = folderDeltaReads.mock.calls.length;
      await search();

      expect(readsAfterFailure).toBeGreaterThan(0);
      expect(folderDeltaReads).toHaveBeenCalledTimes(readsAfterFailure);
      expect(searchedUrls()).toHaveLength(2);
    });

    it('retries a failed folder sync once the pause after the failure has passed', async () => {
      await lastSyncedHoursAgo(ON_DEMAND_DIRECTORY_SYNC_MAX_AGE_MS / HOUR_MS + 1);
      folderDeltaReads.mockRejectedValue(new Error('Graph is unavailable'));
      const query = searchEmailsQuery(features);
      const search = () =>
        query.run(convertUserProfileIdToTypeId(userProfileId), {
          msGraphKeywordSearchQueries: [{ kqlQuery: 'budget', directories: [INBOX.id] }],
        });

      await search();
      const readsAfterFailure = folderDeltaReads.mock.calls.length;
      const failedAt = Date.now();
      const clock = vi
        .spyOn(Date, 'now')
        .mockReturnValue(failedAt + ON_DEMAND_DIRECTORY_SYNC_RETRY_AFTER_MS + 1);
      try {
        await search();
      } finally {
        clock.mockRestore();
      }

      expect(folderDeltaReads.mock.calls.length).toBeGreaterThan(readsAfterFailure);
    });

    it('passes on a revoked sign-in from the folder sync', async () => {
      folderDeltaReads.mockRejectedValue(new UpstreamCredentialRevokedError('invalid_grant'));

      await expect(searchProjectsFolder(features)).rejects.toBeInstanceOf(
        UpstreamCredentialRevokedError,
      );
      expect(searchBatches).not.toHaveBeenCalled();
    });

    it('does not sync for a search without a folder filter', async () => {
      await lastSyncedHoursAgo(24);

      await searchEmailsQuery(features).run(convertUserProfileIdToTypeId(userProfileId), {
        msGraphKeywordSearchQueries: [{ kqlQuery: 'budget' }],
      });

      expect(folderDeltaReads).not.toHaveBeenCalled();
    });

    it('syncs on every list_mailboxes_and_directories call', async () => {
      await lastSyncedHoursAgo(0);
      const tool = new ListMailboxesAndDirectoriesTool(
        syncDirectoriesCommand(features),
        new ListMailboxesAndDirectoriesQuery(db, features),
      );
      const request = { user: { userProfileId } } as McpAuthenticatedRequest;

      await tool.list({}, {} as Context, request);
      const output = await tool.list({}, {} as Context, request);

      expect(folderDeltaReads).toHaveBeenCalledTimes(2);
      assert.ok('mailboxes' in output);
      expect(output.mailboxes[0]?.folders.map(({ id }) => id).sort()).toEqual([
        INBOX.id,
        PROJECTS.id,
      ]);
    });
  });

  describe('scheduled', () => {
    it('leaves the folder cache to the scheduled sync, however old it is', async () => {
      await lastSyncedHoursAgo(24);

      await searchProjectsFolder(featuresWith('scheduled'));

      expect(folderDeltaReads).not.toHaveBeenCalled();
    });
  });
});
