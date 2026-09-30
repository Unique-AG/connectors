import type { TaskPushNotificationConfig } from '@a2a-js/sdk';
import { RequestMalformedError, TaskNotFoundError } from '@a2a-js/sdk/errors';
import type { PushNotificationStore, ServerCallContext } from '@a2a-js/sdk/server';
import { Inject, Injectable } from '@nestjs/common';
import { and, count, eq, isNull } from 'drizzle-orm';
import { typeid } from 'typeid-js';
import { z } from 'zod';
import { CredentialVault } from '../credentials/credential-vault.js';
import { EgressService } from '../credentials/egress.service.js';
import { DRIZZLE, type GatewayDatabase } from '../drizzle/drizzle.module.js';
import { pushNotificationConfigs } from '../drizzle/schema/push-notification-configs.table.js';
import { PgTaskStore } from './pg-task.store.js';

const MAX_CONFIGS_PER_TASK = 5;

const secretsSchema = z.object({
  token: z.string().max(4_096),
  scheme: z.string().max(100),
  credentials: z.string().max(16_384),
});

export interface DeliveryTarget {
  id: string;
  url: string;
  token: string;
  scheme: string;
  credentials: string;
}

/**
 * Webhook registrations for inbound tasks. Only the task owner can register, list or delete them;
 * URLs pass the webhook egress policy and credentials are stored encrypted.
 */
@Injectable()
export class PgPushNotificationStore implements PushNotificationStore {
  public constructor(
    @Inject(DRIZZLE) private readonly database: GatewayDatabase,
    private readonly egress: EgressService,
    private readonly taskStore: PgTaskStore,
    private readonly vault: CredentialVault,
  ) {}

  public async save(
    taskId: string,
    context: ServerCallContext,
    config: TaskPushNotificationConfig,
  ): Promise<void> {
    await this.ownedTask(taskId, context);
    try {
      this.egress.approveWebhook(config.url);
    } catch {
      throw new RequestMalformedError('the webhook URL is not allowed');
    }
    const companyId = context.tenant ?? '';
    const [{ value: existing } = { value: 0 }] = await this.database
      .select({ value: count() })
      .from(pushNotificationConfigs)
      .where(
        and(
          eq(pushNotificationConfigs.companyId, companyId),
          eq(pushNotificationConfigs.taskId, taskId),
        ),
      );
    if (existing >= MAX_CONFIGS_PER_TASK) {
      throw new RequestMalformedError('too many push notification configs for this task');
    }
    // The SDK contract reads the assigned id back from the passed config.
    config.id ||= typeid('pnc').toString();
    const authCiphertext = this.vault.seal(
      JSON.stringify({
        token: config.token ?? '',
        scheme: config.authentication?.scheme ?? '',
        credentials: config.authentication?.credentials ?? '',
      }),
    );
    await this.database
      .insert(pushNotificationConfigs)
      .values({ id: config.id, companyId, taskId, url: config.url, authCiphertext })
      .onConflictDoUpdate({
        target: [pushNotificationConfigs.taskId, pushNotificationConfigs.url],
        set: { authCiphertext, failures: 0, disabledAt: null, updatedAt: new Date() },
      });
  }

  public async load(
    taskId: string,
    context: ServerCallContext,
  ): Promise<TaskPushNotificationConfig[]> {
    await this.ownedTask(taskId, context);
    const targets = await this.targets(context.tenant ?? '', taskId);
    // Webhook secrets are write-only: reads return the configuration without them.
    return targets.map((target) => ({
      tenant: '',
      id: target.id,
      taskId,
      url: target.url,
      token: '',
      authentication: target.scheme ? { scheme: target.scheme, credentials: '' } : undefined,
    }));
  }

  public async delete(taskId: string, context: ServerCallContext, configId?: string) {
    await this.ownedTask(taskId, context);
    await this.database
      .delete(pushNotificationConfigs)
      .where(
        and(
          eq(pushNotificationConfigs.companyId, context.tenant ?? ''),
          eq(pushNotificationConfigs.taskId, taskId),
          ...(configId ? [eq(pushNotificationConfigs.id, configId)] : []),
        ),
      );
  }

  /** Active delivery targets with decrypted credentials, for the sender only. */
  public async targets(companyId: string, taskId: string): Promise<DeliveryTarget[]> {
    const rows = await this.database.query.pushNotificationConfigs.findMany({
      where: and(
        eq(pushNotificationConfigs.companyId, companyId),
        eq(pushNotificationConfigs.taskId, taskId),
        isNull(pushNotificationConfigs.disabledAt),
      ),
    });
    return rows.map((row) => {
      const secrets = secretsSchema.parse(
        JSON.parse(this.vault.open(row.authCiphertext ?? Buffer.alloc(0))),
      );
      return { id: row.id, url: row.url, ...secrets };
    });
  }

  public async target(companyId: string, configId: string): Promise<DeliveryTarget | undefined> {
    const row = await this.database.query.pushNotificationConfigs.findFirst({
      where: and(
        eq(pushNotificationConfigs.companyId, companyId),
        eq(pushNotificationConfigs.id, configId),
        isNull(pushNotificationConfigs.disabledAt),
      ),
    });
    if (!row) {
      return undefined;
    }
    const secrets = secretsSchema.parse(
      JSON.parse(this.vault.open(row.authCiphertext ?? Buffer.alloc(0))),
    );
    return { id: row.id, url: row.url, ...secrets };
  }

  public async recordDelivery(
    companyId: string,
    configId: string,
    delivered: boolean,
    maxFailures: number,
  ) {
    const row = await this.database.query.pushNotificationConfigs.findFirst({
      columns: { failures: true },
      where: and(
        eq(pushNotificationConfigs.companyId, companyId),
        eq(pushNotificationConfigs.id, configId),
      ),
    });
    if (!row) {
      return;
    }
    const failures = delivered ? 0 : row.failures + 1;
    await this.database
      .update(pushNotificationConfigs)
      .set({
        failures,
        updatedAt: new Date(),
        ...(failures >= maxFailures ? { disabledAt: new Date() } : {}),
      })
      .where(
        and(
          eq(pushNotificationConfigs.companyId, companyId),
          eq(pushNotificationConfigs.id, configId),
        ),
      );
  }

  private async ownedTask(taskId: string, context: ServerCallContext): Promise<void> {
    if (!(await this.taskStore.load(taskId, context))) {
      throw new TaskNotFoundError(`Task not found: ${taskId}`);
    }
  }
}
