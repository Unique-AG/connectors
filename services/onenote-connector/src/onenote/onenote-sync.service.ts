import { Client } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { eq } from 'drizzle-orm';
import { Span, TraceService } from 'nestjs-otel';
import type { SyncConfigNamespaced, UniqueConfigNamespaced } from '~/config';
import { DRIZZLE, DrizzleDatabase } from '~/drizzle/drizzle.module';
import { userProfiles } from '~/drizzle/schema';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UniqueContentService } from '~/unique/unique-content.service';
import { UniqueScopeService } from '~/unique/unique-scope.service';
import type { Notebook, Page, Section, SectionGroup } from './onenote.types';
import { OneNoteDeltaService } from './onenote-delta.service';
import { OneNoteGraphService } from './onenote-graph.service';
import { OneNotePermissionsService } from './onenote-permissions.service';

@Injectable()
export class OneNoteSyncService {
  private readonly logger = new Logger(OneNoteSyncService.name);

  public constructor(
    @Inject(DRIZZLE) private readonly drizzle: DrizzleDatabase,
    private readonly config: ConfigService<UniqueConfigNamespaced & SyncConfigNamespaced, true>,
    private readonly trace: TraceService,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly graphService: OneNoteGraphService,
    private readonly deltaService: OneNoteDeltaService,
    private readonly permissionsService: OneNotePermissionsService,
    private readonly scopeService: UniqueScopeService,
    private readonly contentService: UniqueContentService,
  ) {}

  @Span()
  public async syncUser(userProfileId: string): Promise<void> {
    const span = this.trace.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);

    this.logger.log({ userProfileId }, 'Starting sync for user');

    const client = this.graphClientFactory.createClientForUser(userProfileId);

    const deltaResult = await this.deltaService.fetchDelta(client, userProfileId);

    const notebooks = await this.graphService.listNotebooks(client);
    span?.setAttribute('notebook_count', notebooks.length);

    const notebooksToSync = deltaResult.isFullSync
      ? notebooks
      : notebooks.filter((nb) => deltaResult.changedNotebookIds.has(nb.id));

    this.logger.log(
      {
        userProfileId,
        total: notebooks.length,
        toSync: notebooksToSync.length,
        isFullSync: deltaResult.isFullSync,
      },
      'Identified notebooks to sync',
    );

    const rootScopeId = this.config.get('unique.rootScopeId', { infer: true });

    for (const notebook of notebooksToSync) {
      try {
        await this.syncNotebook(client, userProfileId, notebook, rootScopeId);
      } catch (error) {
        this.logger.error(
          { error, notebookId: notebook.id, notebookName: notebook.displayName },
          'Failed to sync notebook',
        );
      }
    }

    this.logger.log(
      { userProfileId, syncedNotebooks: notebooksToSync.length },
      'Completed sync for user',
    );
  }

  @Span()
  private async syncNotebook(
    client: Client,
    userProfileId: string,
    notebook: Notebook,
    rootScopeId: string,
  ): Promise<void> {
    this.logger.debug({ notebookId: notebook.id, name: notebook.displayName }, 'Syncing notebook');

    const notebookScope = await this.scopeService.createScope(
      rootScopeId,
      notebook.displayName,
      false,
    );

    await this.resolveAndSetPermissions(client, notebook, notebookScope.id, userProfileId);

    const sections = await this.graphService.listSections(client, notebook.id);
    const sectionGroups = await this.graphService.listSectionGroups(client, notebook.id);

    for (const section of sections) {
      await this.syncSection(
        client,
        userProfileId,
        section,
        notebookScope.id,
        notebook.displayName,
      );
    }

    for (const group of sectionGroups) {
      await this.syncSectionGroup(
        client,
        userProfileId,
        group,
        notebookScope.id,
        notebook.displayName,
      );
    }
  }

  @Span()
  private async syncSectionGroup(
    client: Client,
    userProfileId: string,
    group: SectionGroup,
    parentScopeId: string,
    notebookName: string,
  ): Promise<void> {
    const groupScope = await this.scopeService.createScope(parentScopeId, group.displayName, true);
    const sections = await this.graphService.listSectionsInGroup(client, group.id);

    for (const section of sections) {
      await this.syncSection(client, userProfileId, section, groupScope.id, notebookName);
    }
  }

  @Span()
  private async syncSection(
    client: Client,
    userProfileId: string,
    section: Section,
    parentScopeId: string,
    notebookName: string,
  ): Promise<void> {
    const sectionScope = await this.scopeService.createScope(
      parentScopeId,
      section.displayName,
      true,
    );
    const pages = await this.graphService.listPages(client, section.id);

    const batchSize = this.config.get('sync.pageBatchSize', { infer: true });

    for (let i = 0; i < pages.length; i += batchSize) {
      const batch = pages.slice(i, i + batchSize);
      await Promise.all(
        batch.map((page) =>
          this.syncPage(
            client,
            userProfileId,
            page,
            sectionScope.id,
            notebookName,
            section.displayName,
          ),
        ),
      );
    }
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
      const htmlContent = await this.graphService.getPageContent(client, page.id);

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

      const htmlStream = new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode(htmlContent));
          controller.close();
        },
      });

      await this.contentService.uploadToStorage(upsertResult.writeUrl, htmlStream, 'text/html');

      await this.contentService.upsertContent({
        storeInternally: true,
        scopeId,
        fileUrl: upsertResult.readUrl,
        input: {
          key: contentKey,
          mimeType: 'text/html',
          title: pageTitle,
          url: oneNoteWebUrl,
        },
      });
    } catch (error) {
      this.logger.warn({ error, pageId: page.id, pageTitle }, 'Failed to sync page');
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
      this.logger.warn(
        { error, notebookId: notebook.id },
        'Failed to resolve permissions for notebook, continuing sync without access control',
      );
    }
  }

  public async getAllUserProfileIds(): Promise<string[]> {
    const profiles = await this.drizzle.select({ id: userProfiles.id }).from(userProfiles);

    return profiles.map((p) => p.id);
  }
}
