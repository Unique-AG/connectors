import { GraphError } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, count, eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import {
  DRIZZLE,
  DrizzleDatabase,
  delegatedAccessDirectories,
  delegatedAccessPipeline,
  userProfiles,
} from '~/db';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';

@Injectable()
export class VerifyDelegatedAccessCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
  ) {}

  @Span()
  public async run(input: { pipelineId: string }): Promise<void> {
    const { pipelineId } = input;

    const [pipeline] = await this.db
      .select({
        delegateUserId: delegatedAccessPipeline.delegateUserId,
        ownerUserId: delegatedAccessPipeline.ownerUserId,
      })
      .from(delegatedAccessPipeline)
      .where(eq(delegatedAccessPipeline.id, pipelineId));

    if (!pipeline) {
      this.logger.warn({ pipelineId, msg: 'Pipeline not found, skipping verification' });
      return;
    }

    const { delegateUserId, ownerUserId } = pipeline;

    const [ownerProfile] = await this.db
      .select({ email: userProfiles.email })
      .from(userProfiles)
      .where(eq(userProfiles.id, ownerUserId));

    const ownerEmail = ownerProfile?.email;
    if (!ownerEmail) {
      this.logger.warn({ pipelineId, ownerUserId, msg: 'Owner email not found, skipping verification' });
      return;
    }

    const client = this.graphClientFactory.createClientForUser(delegateUserId);

    const folders: Array<{ id: string }> = [];
    let response = await client.api(`/users/${ownerEmail}/mailFolders`).top(500).get();
    folders.push(...(response?.value ?? []));

    while (response?.['@odata.nextLink']) {
      response = await client.api(response['@odata.nextLink']).get();
      folders.push(...(response?.value ?? []));
    }

    let hasTransientError = false;

    for (const folder of folders) {
      const folderId = folder.id;
      try {
        await client.api(`/users/${ownerEmail}/mailFolders/${folderId}/messages`).top(1).get();

        await this.db
          .insert(delegatedAccessDirectories)
          .values({ pipelineId, directoryId: folderId })
          .onConflictDoUpdate({
            target: [
              delegatedAccessDirectories.pipelineId,
              delegatedAccessDirectories.directoryId,
            ],
            set: { updatedAt: new Date() },
          });

        this.logger.log({ pipelineId, folderId, msg: 'Directory access confirmed, upserted' });
      } catch (error) {
        if (error instanceof GraphError) {
          if (error.statusCode === 403 || error.statusCode === 404) {
            await this.db
              .delete(delegatedAccessDirectories)
              .where(
                and(
                  eq(delegatedAccessDirectories.pipelineId, pipelineId),
                  eq(delegatedAccessDirectories.directoryId, folderId),
                ),
              );
            this.logger.log({
              pipelineId,
              folderId,
              statusCode: error.statusCode,
              msg: 'Directory access revoked, removed',
            });
            continue;
          }

          if (error.statusCode === 429 || (error.statusCode >= 500 && error.statusCode < 600)) {
            hasTransientError = true;
            this.logger.warn({
              pipelineId,
              folderId,
              statusCode: error.statusCode,
              msg: 'Transient error verifying folder, skipping',
            });
            continue;
          }
        }

        this.logger.error({
          pipelineId,
          folderId,
          error,
          msg: 'Unexpected error during folder verification',
        });
      }
    }

    const [result] = await this.db
      .select({ count: count() })
      .from(delegatedAccessDirectories)
      .where(eq(delegatedAccessDirectories.pipelineId, pipelineId));
    const dirCount = result?.count ?? 0;

    if (dirCount === 0 && !hasTransientError) {
      await this.db
        .delete(delegatedAccessPipeline)
        .where(eq(delegatedAccessPipeline.id, pipelineId));
      this.logger.log({ pipelineId, msg: 'No accessible directories, pipeline deleted' });
      return;
    }

    if (!hasTransientError) {
      await this.db
        .update(delegatedAccessPipeline)
        .set({ lastVerifiedAt: new Date() })
        .where(eq(delegatedAccessPipeline.id, pipelineId));
      this.logger.log({ pipelineId, dirCount, msg: 'Pipeline lastVerifiedAt updated' });
    }
  }
}
