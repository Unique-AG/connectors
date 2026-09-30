import { createHash } from 'node:crypto';
import { type StreamResponse, type Task, TaskState } from '@a2a-js/sdk';
import type { PushNotificationSender, ServerCallContext } from '@a2a-js/sdk/server';
import { Inject, Injectable, Logger, type OnModuleInit } from '@nestjs/common';
import type { JsonObject } from 'absurd-sdk';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';
import { EgressService } from '../credentials/egress.service.js';
import { WorkflowService } from '../workflow/workflow.service.js';
import { PgPushNotificationStore } from './pg-push-notification.store.js';

const PUSH_DELIVER_TASK = 'push.deliver';
const DELIVERY_ATTEMPTS = 6;

interface DeliveryParams extends JsonObject {
  companyId: string;
  configId: string;
  taskId: string;
  contextId: string;
  state: string;
  timestamp: string;
}

/**
 * Push notifications carry only the task id and state; clients fetch content with GetTask under
 * their own authorization. Delivery is a durable absurd task with bounded retries, deduplicated
 * per state change, and a webhook is disabled after repeated failed deliveries.
 */
@Injectable()
export class DurablePushNotificationSender implements PushNotificationSender, OnModuleInit {
  private readonly logger = new Logger(DurablePushNotificationSender.name);

  public constructor(
    private readonly store: PgPushNotificationStore,
    private readonly egress: EgressService,
    private readonly workflow: WorkflowService,
    @Inject(GATEWAY_CONFIG) private readonly config: GatewayConfig,
  ) {}

  public onModuleInit(): void {
    this.workflow.register<DeliveryParams>(PUSH_DELIVER_TASK, (params) => this.deliver(params), {
      defaultMaxAttempts: DELIVERY_ATTEMPTS,
    });
  }

  public async send(response: StreamResponse, context: ServerCallContext, task?: Task) {
    const payload = response.payload;
    if (payload?.$case === 'statusUpdate' && payload.value.status) {
      await this.notify(
        context.tenant ?? '',
        payload.value.taskId,
        payload.value.contextId,
        payload.value.status.state,
      );
    } else if (payload?.$case === 'task' && (task ?? payload.value).status) {
      const value = task ?? payload.value;
      await this.notify(context.tenant ?? '', value.id, value.contextId, value.status?.state ?? 0);
    }
  }

  public async notify(companyId: string, taskId: string, contextId: string, state: TaskState) {
    if (!this.config.pushNotificationsEnabled) {
      return;
    }
    const targets = await this.store.targets(companyId, taskId);
    for (const target of targets) {
      const params: DeliveryParams = {
        companyId,
        configId: target.id,
        taskId,
        contextId,
        state: TaskState[state] ?? String(state),
        timestamp: new Date().toISOString(),
      };
      await this.workflow.spawn(PUSH_DELIVER_TASK, params, {
        idempotencyKey: createHash('sha256')
          .update(`${target.id}:${taskId}:${params.state}`)
          .digest('hex'),
        maxAttempts: DELIVERY_ATTEMPTS,
        retryStrategy: { kind: 'exponential', baseSeconds: 5, maxSeconds: 600 },
      });
    }
  }

  private async deliver(params: DeliveryParams): Promise<{ delivered: boolean }> {
    const target = await this.store.target(params.companyId, params.configId);
    if (!target) {
      return { delivered: false };
    }
    const headers: Record<string, string> = { 'content-type': 'application/json' };
    if (target.token) {
      headers['x-a2a-notification-token'] = target.token;
    }
    if (target.scheme) {
      headers.authorization = `${target.scheme} ${target.credentials}`;
    }
    const body = JSON.stringify({
      statusUpdate: {
        taskId: params.taskId,
        contextId: params.contextId,
        status: { state: params.state, timestamp: params.timestamp },
      },
    });
    let delivered = false;
    try {
      delivered = (await this.egress.postWebhook(target.url, { headers, body })).ok;
    } catch {
      delivered = false;
    }
    await this.store.recordDelivery(
      params.companyId,
      params.configId,
      delivered,
      this.config.pushMaxFailures,
    );
    if (!delivered) {
      this.logger.warn({
        action: 'push.failed',
        companyId: params.companyId,
        taskId: params.taskId,
        configId: params.configId,
      });
      throw new Error('push notification delivery failed');
    }
    return { delivered: true };
  }
}
