import { Client } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { DRIZZLE, DrizzleDatabase } from '~/drizzle/drizzle.module';
import { deltaState } from '~/drizzle/schema';
import type { DriveItemDelta } from './onenote.types';
import { OneNoteGraphService } from './onenote-graph.service';

export interface DeltaResult {
  changedNotebookNames: Set<string>;
  isFullSync: boolean;
}

@Injectable()
export class OneNoteDeltaService {
  private readonly logger = new Logger(OneNoteDeltaService.name);

  public constructor(
    @Inject(DRIZZLE) private readonly drizzle: DrizzleDatabase,
    private readonly graphService: OneNoteGraphService,
  ) {}

  @Span()
  public async fetchDelta(client: Client, userProfileId: string): Promise<DeltaResult> {
    const existing = await this.drizzle.query.deltaState.findFirst({
      where: eq(deltaState.userProfileId, userProfileId),
    });

    let items: DriveItemDelta[];
    let nextDeltaLink: string;
    let isFullSync = !existing;

    try {
      const result = await this.graphService.getDelta(client, existing?.deltaLink);
      items = result.items;
      nextDeltaLink = result.nextDeltaLink;
    } catch (error: unknown) {
      const statusCode = (error as { statusCode?: number }).statusCode;
      const isGone =
        statusCode === 410 || (error instanceof Error && error.message?.includes('resyncRequired'));
      if (isGone) {
        this.logger.warn({ userProfileId }, 'Delta token expired (410 Gone), performing full sync');
        isFullSync = true;
        const result = await this.graphService.getDelta(client);
        items = result.items;
        nextDeltaLink = result.nextDeltaLink;
      } else {
        throw error;
      }
    }

    await this.persistDeltaLink(userProfileId, nextDeltaLink, 'success');

    const changedNotebookNames = this.filterOneNoteItems(items);

    this.logger.log(
      {
        userProfileId,
        isFullSync,
        totalDeltaItems: items.length,
        changedNotebooks: changedNotebookNames.size,
      },
      'Completed delta fetch',
    );

    return { changedNotebookNames, isFullSync };
  }

  private filterOneNoteItems(items: DriveItemDelta[]): Set<string> {
    const notebookNames = new Set<string>();

    for (const item of items) {
      const isOneNotePackage = item.package?.type === 'oneNote';
      const isOneNoteFile = item.name?.endsWith('.one') || item.name?.endsWith('.onetoc2');

      if (isOneNotePackage && item.name) {
        notebookNames.add(item.name);
      } else if (isOneNoteFile) {
        const notebookName = this.extractNotebookNameFromPath(item.parentReference?.path);
        if (notebookName) {
          notebookNames.add(notebookName);
        } else if (item.parentReference?.name) {
          notebookNames.add(item.parentReference.name);
        }
      }
    }

    return notebookNames;
  }

  private extractNotebookNameFromPath(path?: string): string | undefined {
    if (!path) return undefined;
    const rootPrefix = '/drive/root:';
    if (!path.startsWith(rootPrefix)) return undefined;
    const relativePath = path.slice(rootPrefix.length);
    const segments = relativePath.split('/').filter(Boolean);
    return segments[0];
  }

  private async persistDeltaLink(
    userProfileId: string,
    deltaLink: string,
    status: string,
  ): Promise<void> {
    await this.drizzle
      .insert(deltaState)
      .values({
        userProfileId,
        deltaLink,
        lastSyncedAt: new Date(),
        lastSyncStatus: status,
      })
      .onConflictDoUpdate({
        target: deltaState.userProfileId,
        set: {
          deltaLink,
          lastSyncedAt: new Date(),
          lastSyncStatus: status,
        },
      });
  }

  public async clearDelta(userProfileId: string): Promise<void> {
    await this.drizzle.delete(deltaState).where(eq(deltaState.userProfileId, userProfileId));
  }

  public async disableSync(userProfileId: string): Promise<void> {
    const existing = await this.drizzle.query.deltaState.findFirst({
      where: eq(deltaState.userProfileId, userProfileId),
    });

    if (existing) {
      await this.drizzle
        .update(deltaState)
        .set({ lastSyncStatus: 'disabled' })
        .where(eq(deltaState.userProfileId, userProfileId));
    } else {
      await this.drizzle.insert(deltaState).values({
        userProfileId,
        deltaLink: '',
        lastSyncStatus: 'disabled',
      });
    }
  }

  public async enableSync(userProfileId: string): Promise<void> {
    const existing = await this.drizzle.query.deltaState.findFirst({
      where: eq(deltaState.userProfileId, userProfileId),
    });

    if (existing?.lastSyncStatus === 'disabled') {
      await this.drizzle
        .update(deltaState)
        .set({ lastSyncStatus: 'enabled' })
        .where(eq(deltaState.userProfileId, userProfileId));
    }
  }

  public async isSyncDisabled(userProfileId: string): Promise<boolean> {
    const state = await this.drizzle.query.deltaState.findFirst({
      where: eq(deltaState.userProfileId, userProfileId),
    });
    return state?.lastSyncStatus === 'disabled';
  }

  public async getDeltaStatus(userProfileId: string) {
    return this.drizzle.query.deltaState.findFirst({
      where: eq(deltaState.userProfileId, userProfileId),
    });
  }
}
