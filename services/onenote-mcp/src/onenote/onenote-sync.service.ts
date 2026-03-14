import { Client } from '@microsoft/microsoft-graph-client';
import { CACHE_MANAGER } from '@nestjs/cache-manager';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Cache } from 'cache-manager';
import { and, eq, isNotNull } from 'drizzle-orm';
import { Span, TraceService } from 'nestjs-otel';
import type { SyncConfigNamespaced, UniqueConfigNamespaced } from '~/config';
import { DRIZZLE, DrizzleDatabase } from '~/drizzle/drizzle.module';
import { userProfiles } from '~/drizzle/schema';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { withThrottleRetry } from '~/msgraph/with-throttle-retry';
import { UniqueContentService } from '~/unique/unique-content.service';
import { ScopeAccessEntityType, ScopeAccessType } from '~/unique/unique.dtos';
import { UniqueScopeService } from '~/unique/unique-scope.service';
import { UniqueUserService } from '~/unique/unique-user.service';
import { normalizeError } from '~/utils/normalize-error';
import type { Notebook, Page, Section, SectionGroup } from './onenote.types';
import { OneNoteDeltaService } from './onenote-delta.service';
import { OneNoteGraphService } from './onenote-graph.service';
import { OneNotePermissionsService } from './onenote-permissions.service';

@Injectable()
export class OneNoteSyncService {
  private readonly logger = new Logger(OneNoteSyncService.name);

  private static readonly SCOPE_IDS_CACHE_PREFIX = 'user_scope_ids:';
  private readonly pendingSyncs = new Map<string, NodeJS.Timeout>();
  private readonly activeSyncs = new Set<string>();

  public constructor(
    @Inject(DRIZZLE) private readonly drizzle: DrizzleDatabase,
    @Inject(CACHE_MANAGER) private readonly cacheManager: Cache,
    private readonly config: ConfigService<UniqueConfigNamespaced & SyncConfigNamespaced, true>,
    private readonly trace: TraceService,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly graphService: OneNoteGraphService,
    private readonly deltaService: OneNoteDeltaService,
    private readonly permissionsService: OneNotePermissionsService,
    private readonly scopeService: UniqueScopeService,
    private readonly contentService: UniqueContentService,
    private readonly userService: UniqueUserService,
  ) {}

  public isSyncRunning(userProfileId: string): boolean {
    return this.activeSyncs.has(userProfileId);
  }

  public debouncedSync(userProfileId: string): void {
    const existing = this.pendingSyncs.get(userProfileId);
    if (existing) {
      clearTimeout(existing);
    }

    const debounceMs = this.config.get('sync.debounceMs', { infer: true });

    const timeout = setTimeout(() => {
      this.pendingSyncs.delete(userProfileId);
      this.logger.log({ userProfileId }, 'Debounced sync triggered');
      this.syncUser(userProfileId).catch((err) => {
        this.logger.warn({ userProfileId, error: String(err) }, 'Debounced sync failed');
      });
    }, debounceMs);

    this.pendingSyncs.set(userProfileId, timeout);
  }

  @Span()
  public async syncUser(userProfileId: string): Promise<void> {
    if (this.activeSyncs.has(userProfileId)) {
      this.logger.log({ userProfileId }, 'Sync already running for user, skipping');
      return;
    }

    this.activeSyncs.add(userProfileId);
    try {
      await this.executeSyncUser(userProfileId);
    } finally {
      this.activeSyncs.delete(userProfileId);
    }
  }

  private async executeSyncUser(userProfileId: string): Promise<void> {
    const span = this.trace.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);

    if (await this.deltaService.isSyncDisabled(userProfileId)) {
      this.logger.debug({ userProfileId }, 'Sync disabled for user, skipping');
      return;
    }

    this.logger.log({ userProfileId }, 'Starting sync for user');

    const client = this.graphClientFactory.createClientForUser(userProfileId);

    const deltaResult = await this.deltaService.fetchDelta(client, userProfileId);

    const notebooks = await withThrottleRetry(
      () => this.graphService.listNotebooks(client),
      'listNotebooks',
    );
    span?.setAttribute('notebook_count', notebooks.length);

    this.logger.log(
      {
        userProfileId,
        notebookCount: notebooks.length,
        notebooks: notebooks.map((nb) => ({ id: nb.id, name: nb.displayName })),
      },
      'OneNote notebooks discovered',
    );

    const notebooksToSync = deltaResult.isFullSync
      ? notebooks
      : notebooks.filter((nb) => deltaResult.changedNotebookNames.has(nb.displayName));

    this.logger.log(
      {
        userProfileId,
        total: notebooks.length,
        toSync: notebooksToSync.length,
        isFullSync: deltaResult.isFullSync,
        notebooksToSync: notebooksToSync.map((nb) => ({ id: nb.id, name: nb.displayName })),
      },
      'Identified notebooks to sync',
    );

    const rootScopeId = this.config.get('unique.rootScopeId', { infer: true });

    const userScope = await this.scopeService.createScope(rootScopeId, userProfileId, false);

    this.logger.log(
      { userProfileId, uniqueUserScopeId: userScope.id, parentScopeId: rootScopeId },
      'Unique user scope created',
    );

    await this.tryGrantUserScopeAccess(userProfileId, userScope.id);

    let syncedCount = 0;
    let failedCount = 0;
    const sectionScopeIds: string[] = [];

    for (const notebook of notebooksToSync) {
      try {
        const notebookScopeIds = await this.syncNotebook(
          client,
          userProfileId,
          notebook,
          userScope.id,
        );
        sectionScopeIds.push(...notebookScopeIds);
        syncedCount++;
      } catch (error) {
        failedCount++;
        const normalized = normalizeError(error);
        this.logger.error(
          {
            notebookId: notebook.id,
            notebookName: notebook.displayName,
            errorMessage: normalized.message,
            errorStack: normalized.stack,
            errorName: normalized.name,
          },
          'Failed to sync notebook',
        );
      }
    }

    if (sectionScopeIds.length > 0) {
      await this.cacheManager.set(
        `${OneNoteSyncService.SCOPE_IDS_CACHE_PREFIX}${userProfileId}`,
        sectionScopeIds,
      );
    }

    if (failedCount === 0) {
      await this.deltaService.commitDeltaLink(userProfileId, deltaResult.nextDeltaLink);
    } else {
      this.logger.warn(
        { userProfileId, failedCount, syncedCount },
        'Skipping delta commit due to sync failures — next run will retry',
      );
    }

    this.logger.log(
      { userProfileId, syncedNotebooks: syncedCount, failedNotebooks: failedCount },
      'Completed sync for user',
    );
  }

  @Span()
  private async syncNotebook(
    client: Client,
    userProfileId: string,
    notebook: Notebook,
    rootScopeId: string,
  ): Promise<string[]> {
    this.logger.log({ notebookId: notebook.id, name: notebook.displayName }, 'Syncing notebook');

    const notebookScope = await this.scopeService.createScope(
      rootScopeId,
      notebook.displayName,
      false,
    );

    this.logger.log(
      {
        onenoteNotebookId: notebook.id,
        notebookName: notebook.displayName,
        uniqueNotebookScopeId: notebookScope.id,
        parentScopeId: rootScopeId,
      },
      'Unique notebook scope created',
    );

    await this.resolveAndSetPermissions(client, notebook, notebookScope.id, userProfileId);

    const sections = await withThrottleRetry(
      () => this.graphService.listSections(client, notebook.id),
      `listSections(${notebook.displayName})`,
    );
    const sectionGroups = await withThrottleRetry(
      () => this.graphService.listSectionGroups(client, notebook.id),
      `listSectionGroups(${notebook.displayName})`,
    );

    this.logger.log(
      {
        notebookId: notebook.id,
        notebookName: notebook.displayName,
        sectionCount: sections.length,
        sections: sections.map((s) => ({ id: s.id, name: s.displayName })),
        sectionGroupCount: sectionGroups.length,
        sectionGroups: sectionGroups.map((sg) => ({ id: sg.id, name: sg.displayName })),
      },
      'OneNote notebook contents discovered',
    );

    const scopeIds: string[] = [];

    for (const section of sections) {
      const sectionScopeId = await this.syncSection(
        client,
        userProfileId,
        section,
        notebookScope.id,
        notebook.displayName,
      );
      scopeIds.push(sectionScopeId);
    }

    for (const group of sectionGroups) {
      const groupScopeIds = await this.syncSectionGroup(
        client,
        userProfileId,
        group,
        notebookScope.id,
        notebook.displayName,
      );
      scopeIds.push(...groupScopeIds);
    }

    return scopeIds;
  }

  @Span()
  private async syncSectionGroup(
    client: Client,
    userProfileId: string,
    group: SectionGroup,
    parentScopeId: string,
    notebookName: string,
  ): Promise<string[]> {
    const groupScope = await this.scopeService.createScope(parentScopeId, group.displayName, true);

    this.logger.log(
      {
        onenoteSectionGroupId: group.id,
        sectionGroupName: group.displayName,
        uniqueSectionGroupScopeId: groupScope.id,
        parentScopeId,
      },
      'Unique section group scope created',
    );

    const sections = await withThrottleRetry(
      () => this.graphService.listSectionsInGroup(client, group.id),
      `listSectionsInGroup(${group.displayName})`,
    );

    this.logger.log(
      {
        sectionGroupId: group.id,
        sectionGroupName: group.displayName,
        sectionCount: sections.length,
        sections: sections.map((s) => ({ id: s.id, name: s.displayName })),
      },
      'OneNote section group contents discovered',
    );

    const scopeIds: string[] = [];
    for (const section of sections) {
      const sectionScopeId = await this.syncSection(
        client,
        userProfileId,
        section,
        groupScope.id,
        notebookName,
      );
      scopeIds.push(sectionScopeId);
    }
    return scopeIds;
  }

  @Span()
  private async syncSection(
    client: Client,
    userProfileId: string,
    section: Section,
    parentScopeId: string,
    notebookName: string,
  ): Promise<string> {
    const sectionScope = await this.scopeService.createScope(
      parentScopeId,
      section.displayName,
      true,
    );

    this.logger.log(
      {
        onenoteSectionId: section.id,
        sectionName: section.displayName,
        uniqueSectionScopeId: sectionScope.id,
        parentScopeId,
        notebookName,
      },
      'Unique section scope created',
    );

    const pages = await withThrottleRetry(
      () => this.graphService.listPages(client, section.id),
      `listPages(${section.displayName})`,
    );

    this.logger.log(
      {
        sectionId: section.id,
        sectionName: section.displayName,
        notebookName,
        pageCount: pages.length,
        pages: pages.map((p) => ({
          id: p.id,
          title: p.title || 'Untitled Page',
          lastModified: p.lastModifiedDateTime,
        })),
      },
      'OneNote section pages discovered',
    );

    for (const page of pages) {
      await this.syncPage(
        client,
        userProfileId,
        page,
        sectionScope.id,
        notebookName,
        section.displayName,
      );
    }

    return sectionScope.id;
  }

  @Span()
  private async syncPage(
    client: Client,
    userProfileId: string,
    page: Page,
    scopeId: string,
    notebookName: string,
    sectionName: string,
  ): Promise<void> {
    const pageTitle = page.title || 'Untitled Page';
    const contentKey = `onenote:${userProfileId}:${page.id}`;
    const oneNoteWebUrl = page.links?.oneNoteWebUrl?.href;

    try {
      this.logger.debug(
        { pageId: page.id, pageTitle, contentKey, scopeId, notebookName, sectionName },
        'Syncing page to Unique',
      );

      const htmlContent = await withThrottleRetry(
        () => this.graphService.getPageContent(client, page.id),
        `getPageContent(${pageTitle})`,
      );

      this.logger.debug(
        { pageId: page.id, htmlLength: htmlContent.length },
        'Fetched page HTML content from Graph API',
      );

      const metadata: Record<string, string> = {
        createdDateTime: page.createdDateTime,
        lastModifiedDateTime: page.lastModifiedDateTime,
        notebookName,
        sectionName,
      };
      if (oneNoteWebUrl) {
        metadata.oneNoteWebUrl = oneNoteWebUrl;
      }

      const upsertResult = await this.contentService.upsertContent({
        storeInternally: true,
        scopeId,
        input: {
          key: contentKey,
          mimeType: 'text/html',
          title: pageTitle,
          byteSize: Buffer.byteLength(htmlContent, 'utf-8'),
          url: oneNoteWebUrl,
          metadata,
        },
      });

      this.logger.log(
        {
          onenotePageId: page.id,
          pageTitle,
          uniqueContentId: upsertResult.id,
          uniqueContentKey: upsertResult.key,
          uniqueScopeId: scopeId,
          updatedAt: upsertResult.updatedAt,
          notebookName,
          sectionName,
          byteSize: Buffer.byteLength(htmlContent, 'utf-8'),
        },
        'Page upserted in Unique',
      );

      const htmlStream = new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode(htmlContent));
          controller.close();
        },
      });

      const byteSize = Buffer.byteLength(htmlContent, 'utf-8');
      await this.contentService.uploadToStorage(
        upsertResult.writeUrl,
        htmlStream,
        'text/html',
        byteSize,
      );

      await this.contentService.upsertContent({
        storeInternally: true,
        scopeId,
        fileUrl: upsertResult.readUrl,
        input: {
          key: contentKey,
          mimeType: 'text/html',
          title: pageTitle,
          byteSize: Buffer.byteLength(htmlContent, 'utf-8'),
          url: oneNoteWebUrl,
          metadata,
        },
      });

      this.logger.log(
        {
          onenotePageId: page.id,
          pageTitle,
          uniqueContentId: upsertResult.id,
        },
        'Page content uploaded and finalized in Unique',
      );
    } catch (error) {
      const normalized = normalizeError(error);
      this.logger.warn(
        {
          pageId: page.id,
          pageTitle,
          errorMessage: normalized.message,
          errorStack: normalized.stack,
          errorName: normalized.name,
        },
        'Failed to sync page',
      );
    }
  }

  private async tryGrantUserScopeAccess(
    userProfileId: string,
    userScopeId: string,
  ): Promise<void> {
    const profile = await this.drizzle.query.userProfiles.findFirst({
      where: eq(userProfiles.id, userProfileId),
      columns: { email: true },
    });

    if (!profile?.email) {
      this.logger.log(
        { userProfileId },
        'User profile has no email — skipping Unique user permission grant. The onenote-mcp sync and tools will still work via the service user.',
      );
      return;
    }

    const uniqueUser = await this.userService.findUserByEmail(profile.email);

    if (!uniqueUser) {
      this.logger.log(
        { userProfileId },
        'User not found on the Unique platform — skipping user-level permission grant on the scope. The onenote-mcp sync and tools will still work via the service user.',
      );
      return;
    }

    try {
      await this.scopeService.addScopeAccesses(userScopeId, [
        {
          entityId: uniqueUser.id,
          entityType: ScopeAccessEntityType.User,
          type: ScopeAccessType.Read,
        },
      ]);

      this.logger.log(
        { userProfileId, uniqueUserId: uniqueUser.id, userScopeId },
        'Granted read access on user scope to matched Unique user',
      );
    } catch (error) {
      const normalized = normalizeError(error);
      this.logger.warn(
        {
          userProfileId,
          uniqueUserId: uniqueUser.id,
          userScopeId,
          errorMessage: normalized.message,
          errorName: normalized.name,
        },
        'Failed to grant user-level scope access — sync will continue without it',
      );
    }
  }

  private async resolveAndSetPermissions(
    client: Client,
    notebook: Notebook,
    scopeId: string,
    userProfileId: string,
  ): Promise<void> {
    try {
      const driveItem = await this.graphService.getNotebookDriveItem(client, notebook.id);
      if (!driveItem) {
        this.logger.debug(
          { notebookId: notebook.id },
          'Could not resolve drive item for notebook, skipping permission sync',
        );
        return;
      }

      const permissions = await this.graphService.getNotebookPermissions(
        client,
        driveItem.driveId,
        driveItem.itemId,
      );

      const ownerProfile = await this.drizzle.query.userProfiles.findFirst({
        where: eq(userProfiles.id, userProfileId),
        columns: { email: true },
      });

      const accesses = await this.permissionsService.resolveNotebookAccesses(
        client,
        permissions,
        ownerProfile?.email ?? undefined,
      );

      if (accesses.length > 0) {
        await this.scopeService.addScopeAccesses(scopeId, accesses);
      }
    } catch (error) {
      const normalized = normalizeError(error);
      this.logger.warn(
        {
          notebookId: notebook.id,
          errorMessage: normalized.message,
          errorStack: normalized.stack,
          errorName: normalized.name,
        },
        'Failed to resolve permissions for notebook, continuing sync without access control',
      );
    }
  }

  public async getAllUserProfileIds(): Promise<string[]> {
    const profiles = await this.drizzle
      .select({ id: userProfiles.id })
      .from(userProfiles)
      .where(and(isNotNull(userProfiles.accessToken), isNotNull(userProfiles.refreshToken)));

    return profiles.map((p) => p.id);
  }
}
