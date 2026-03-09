import { Client } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { DRIZZLE, DrizzleDatabase } from '~/drizzle/drizzle.module';
import { deltaState } from '~/drizzle/schema';
import type { DriveItemDelta } from './onenote.types';
import { OneNoteGraphService } from './onenote-graph.service';

export interface DeltaResult {
  changedNotebookIds: Set<string>;
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
      const isGone = error instanceof Error && error.message?.includes('410');
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

    const changedNotebookIds = this.filterOneNoteItems(items);

    this.logger.log(
      {
        userProfileId,
        isFullSync,
        totalDeltaItems: items.length,
        changedNotebooks: changedNotebookIds.size,
      },
      'Completed delta fetch',
    );

    return { changedNotebookIds, isFullSync };
  }

  private filterOneNoteItems(items: DriveItemDelta[]): Set<string> {
    const notebookIds = new Set<string>();

    for (const item of items) {
      const isOneNotePackage = item.package?.type === 'oneNote';
      const isOneNoteFile = item.name?.endsWith('.one') || item.name?.endsWith('.onetoc2');

      if (isOneNotePackage || isOneNoteFile) {
        notebookIds.add(item.id);

        if (item.parentReference?.id) {
          notebookIds.add(item.parentReference.id);
        }
      }
    }

    return notebookIds;
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

  public async getDeltaStatus(userProfileId: string) {
    return this.drizzle.query.deltaState.findFirst({
      where: eq(deltaState.userProfileId, userProfileId),
    });
  }
}
