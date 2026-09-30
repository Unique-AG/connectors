import { Inject, Injectable, NotFoundException } from '@nestjs/common';
import type { RequestIdentity } from '../auth/identity.guard.js';
import { ResourceAuthorizationService } from '../auth/resource-authorization.service.js';
import { safeFilename } from '../bridge/file-policy.js';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';
import { ContextRepository } from '../drizzle/context.repository.js';
import { UniqueInternalClient } from '../unique/unique-internal.client.js';
import { taskFileUrl } from './inbound-translation.js';
import { PgTaskStore } from './pg-task.store.js';

/**
 * Serves a file artifact only to the task owner, only for files the task exposed, and only
 * through core's own content access check for the same user and chat.
 */
@Injectable()
export class InboundFilesService {
  public constructor(
    private readonly authorization: ResourceAuthorizationService,
    private readonly contexts: ContextRepository,
    private readonly taskStore: PgTaskStore,
    private readonly unique: UniqueInternalClient,
    @Inject(GATEWAY_CONFIG) private readonly config: GatewayConfig,
  ) {}

  public async download(
    identity: RequestIdentity,
    publicationId: string,
    taskId: string,
    contentId: string,
  ) {
    const task = await this.contexts.findTask(taskId);
    if (
      !task?.chatId ||
      task.companyId !== identity.companyId ||
      task.userId !== identity.userId ||
      task.publicationId !== publicationId
    ) {
      throw new NotFoundException('file not found');
    }
    await this.authorization.publication(identity, publicationId);
    const snapshot = await this.taskStore.findSnapshot(identity.companyId, taskId);
    if (!snapshot || !taskFileUrl(snapshot, contentId)) {
      throw new NotFoundException('file not found');
    }
    const file = await this.unique.downloadContent(
      identity,
      contentId,
      task.chatId,
      this.config.maxRemoteFileBytes,
    );
    return { ...file, filename: safeFilename(file.filename, contentId) };
  }
}
