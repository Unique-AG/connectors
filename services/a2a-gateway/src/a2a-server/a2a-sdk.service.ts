import { setTimeout as delay } from 'node:timers/promises';
import type { SendMessageRequest, StreamResponse, SubscribeToTaskRequest, Task } from '@a2a-js/sdk';
import { TaskNotFoundError, UnsupportedOperationError } from '@a2a-js/sdk/errors';
import {
  DefaultExecutionEventBusManager,
  DefaultRequestHandler,
  JsonRpcTransportHandler,
  ServerCallContext,
} from '@a2a-js/sdk/server';
import { Inject, Injectable } from '@nestjs/common';
import type { RequestIdentity } from '../auth/identity.guard.js';
import { ResourceAuthorizationService } from '../auth/resource-authorization.service.js';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';
import { InboundAdmissionService } from './inbound-admission.service.js';
import { InboundAgentExecutor } from './inbound-agent.executor.js';
import { isTerminal } from './inbound-translation.js';
import { PgPushNotificationStore } from './pg-push-notification.store.js';
import { PgTaskStore } from './pg-task.store.js';
import { PublicationService } from './publication.service.js';
import { DurablePushNotificationSender } from './push-notification.sender.js';

const SNAPSHOT_POLL_MS = 1_000;

interface JsonRpcCall {
  body: unknown;
  headers: Record<string, string | string[] | undefined>;
  identity: RequestIdentity;
  publicationId: string;
  requestedVersion?: string;
}

interface DurableSubscription {
  buses: DefaultExecutionEventBusManager;
  taskStore: PgTaskStore;
  timeoutMs: number;
}

class AdmittingRequestHandler extends DefaultRequestHandler {
  public constructor(
    private readonly admission: InboundAdmissionService,
    private readonly durable: DurableSubscription,
    ...handler: ConstructorParameters<typeof DefaultRequestHandler>
  ) {
    super(...handler);
  }

  public override async sendMessage(params: SendMessageRequest, context: ServerCallContext) {
    const admission = await this.admission.admit(params, context);
    return 'duplicate' in admission
      ? admission.duplicate
      : super.sendMessage(admission.params, context);
  }

  public override async *sendMessageStream(params: SendMessageRequest, context: ServerCallContext) {
    const admission = await this.admission.admit(params, context);
    if ('params' in admission) {
      yield* super.sendMessageStream(admission.params, context);
      return;
    }
    yield { payload: { $case: 'task', value: admission.duplicate } } satisfies StreamResponse;
    if (!isTerminal(admission.duplicate)) {
      yield* this.resubscribe({ tenant: '', id: admission.duplicate.id }, context);
    }
  }

  /**
   * Attaches to the live execution when this replica runs it; otherwise (another replica, or a
   * restart) follows the durable task snapshot so a reconnect never starts another execution.
   */
  public override async *resubscribe(
    params: SubscribeToTaskRequest,
    context: ServerCallContext,
  ): AsyncGenerator<StreamResponse, void, undefined> {
    if (this.durable.buses.getByTaskId(params.id, context)) {
      yield* super.resubscribe(params, context);
      return;
    }
    let task = await this.durable.taskStore.load(params.id, context);
    if (!task) {
      throw new TaskNotFoundError(`Task not found: ${params.id}`);
    }
    if (isTerminal(task)) {
      throw new UnsupportedOperationError('the task is terminal and cannot be subscribed to');
    }
    yield { payload: { $case: 'task', value: task } };
    const deadline = Date.now() + this.durable.timeoutMs;
    let last = JSON.stringify(task);
    while (Date.now() < deadline) {
      await delay(SNAPSHOT_POLL_MS);
      const next: Task | undefined = await this.durable.taskStore.load(params.id, context);
      if (!next) {
        return;
      }
      const serialized = JSON.stringify(next);
      if (serialized !== last) {
        last = serialized;
        task = next;
        yield { payload: { $case: 'task', value: task } };
      }
      if (isTerminal(task)) {
        return;
      }
    }
  }
}

@Injectable()
export class A2aSdkService {
  private readonly buses = new DefaultExecutionEventBusManager();

  public constructor(
    private readonly admission: InboundAdmissionService,
    private readonly authorization: ResourceAuthorizationService,
    private readonly executor: InboundAgentExecutor,
    private readonly publications: PublicationService,
    private readonly taskStore: PgTaskStore,
    private readonly pushStore: PgPushNotificationStore,
    private readonly pushSender: DurablePushNotificationSender,
    @Inject(GATEWAY_CONFIG) private readonly config: GatewayConfig,
  ) {}

  public async handleJsonRpc(call: JsonRpcCall) {
    const card = await this.publications.getTenantAgentCard(
      call.identity.companyId,
      call.publicationId,
    );
    const requestHandler = new AdmittingRequestHandler(
      this.admission,
      { buses: this.buses, taskStore: this.taskStore, timeoutMs: this.config.streamTimeoutMs },
      card,
      this.taskStore,
      this.executor,
      this.buses,
      this.config.pushNotificationsEnabled ? this.pushStore : undefined,
      this.config.pushNotificationsEnabled ? this.pushSender : undefined,
      async () => {
        await this.authorization.publication(call.identity, call.publicationId);
        return card;
      },
    );
    const context = new ServerCallContext({
      tenant: call.identity.companyId,
      user: { isAuthenticated: true, userName: call.identity.userId },
      requestedVersion: call.requestedVersion,
      state: new Map<string, unknown>([
        ['headers', call.headers],
        ['publicationId', call.publicationId],
        ['roles', call.identity.roles],
      ]),
    });
    const body =
      typeof call.body === 'string' || (typeof call.body === 'object' && call.body !== null)
        ? (call.body as string | Record<string, unknown>)
        : {};
    return new JsonRpcTransportHandler(requestHandler).handle(body, context);
  }
}
