import { setTimeout as delay } from 'node:timers/promises';
import { type AgentCard, type Message, type Part, Role } from '@a2a-js/sdk';
import { type Client, ClientFactory, JsonRpcTransportFactory } from '@a2a-js/sdk/client';
import {
  A2AError,
  ContentTypeNotSupportedError,
  TaskNotCancelableError,
  TaskNotFoundError,
  UnsupportedOperationError,
  VersionNotSupportedError,
} from '@a2a-js/sdk/errors';
import {
  ForbiddenException,
  Inject,
  Injectable,
  Logger,
  NotFoundException,
  type OnModuleInit,
} from '@nestjs/common';
import type { JsonValue, TaskContext } from 'absurd-sdk';
import { z } from 'zod';
import type { RequestIdentity } from '../auth/identity.guard.js';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';
import { CredentialProviderService } from '../credentials/credential-provider.service.js';
import { ConnectionRepository } from '../drizzle/connection.repository.js';
import {
  ACTIVE_EXECUTION_STATES,
  type Execution,
  ExecutionRepository,
  type ExecutionState,
} from '../drizzle/execution.repository.js';
import { UniqueInternalClient } from '../unique/unique-internal.client.js';
import { UniqueInternalError } from '../unique/unique-internal.error.js';
import { WorkflowService } from '../workflow/workflow.service.js';
import { ChatWriter } from './chat-writer.js';
import { OUTBOUND_RUN_TASK, type OutboundRunParams } from './outbound-execution.service.js';
import { RemoteTurn, renderParts } from './remote-turn.js';

const WATCH_INTERVAL_MS = 2_000;
const MAX_POLL_INTERVAL_MS = 5_000;
const MAX_CONSECUTIVE_POLL_FAILURES = 12;
const OUTPUT_MODES = ['text/plain', 'text/markdown', 'application/json'];

const userMessage = z.object({ text: z.string().nullish() });

const abortState = z.object({ userAbortedAt: z.string().nullish() });

const parentTurn = z.object({ parentChatId: z.string(), parentMessageId: z.string() });

type OutcomeState = Extract<ExecutionState, 'completed' | 'failed' | 'canceled' | 'unknown'>;

/** A decided end of a run. Anything else thrown is infrastructure and lets absurd retry. */
class Outcome {
  public constructor(
    public readonly state: OutcomeState,
    public readonly text: string,
    public readonly reason?: string,
  ) {}
}

class Interrupted extends Error {
  public constructor(public readonly kind: 'cancel' | 'deadline') {
    super(kind);
  }
}

const MESSAGES = {
  connection:
    'The external agent connection of this space is disabled or not verified. Ask a space administrator to check its configuration.',
  forbidden: 'You are no longer allowed to use this external agent.',
  version: 'The external agent does not support the A2A protocol version 1.0.',
  unsupportedInput: 'The external agent does not accept text messages.',
  unsupported: 'The external agent does not support this request.',
  failed: 'The external agent could not complete the request.',
  unknown:
    'The external agent may have received this request, but its outcome is unknown. Check with the external provider before retrying.',
  unreachable:
    'The external agent became unreachable while working on this request. Its outcome is unknown.',
  timeout: 'The external agent did not finish in time.',
  canceled: 'The request was canceled.',
  interaction:
    'The external agent needs additional input or authorization, which this space does not support yet.',
  empty: 'The external agent returned no answer.',
} as const;

function textPart(value: string): Part {
  return {
    content: { $case: 'text', value },
    metadata: undefined,
    filename: '',
    mediaType: 'text/plain',
  };
}

function acceptsText(card: AgentCard): boolean {
  const modes = card.defaultInputModes ?? [];
  return !modes.length || modes.some((mode) => ['text', 'text/plain'].includes(mode));
}

function peerFailure(error: unknown): Outcome | undefined {
  if (error instanceof VersionNotSupportedError) {
    return new Outcome('failed', MESSAGES.version, 'version');
  }
  if (error instanceof ContentTypeNotSupportedError) {
    return new Outcome('failed', MESSAGES.unsupportedInput, 'content-type');
  }
  if (error instanceof UnsupportedOperationError) {
    return new Outcome('failed', MESSAGES.unsupported, 'unsupported');
  }
  if (error instanceof A2AError) {
    return new Outcome('failed', MESSAGES.failed, `peer-error:${error.name}`);
  }
  return undefined;
}

@Injectable()
export class OutboundRunner implements OnModuleInit {
  private readonly logger = new Logger(OutboundRunner.name);

  public constructor(
    private readonly connections: ConnectionRepository,
    private readonly credentials: CredentialProviderService,
    private readonly executions: ExecutionRepository,
    private readonly unique: UniqueInternalClient,
    private readonly workflow: WorkflowService,
    @Inject(GATEWAY_CONFIG) private readonly config: GatewayConfig,
  ) {}

  public onModuleInit(): void {
    this.workflow.register<OutboundRunParams>(OUTBOUND_RUN_TASK, (params, context) =>
      this.run(params, context),
    );
  }

  public async run(params: OutboundRunParams, context: TaskContext): Promise<JsonValue> {
    const identity: RequestIdentity = {
      companyId: params.companyId,
      userId: params.userId,
      roles: [],
    };
    const execution = await this.executions.findOwned(identity, params.executionId);
    if (!ACTIVE_EXECUTION_STATES.includes(execution.state)) {
      return { state: execution.state };
    }
    const writer = new ChatWriter(
      this.unique,
      identity,
      execution.chatId,
      execution.assistantMessageId,
    );
    let outcome: Outcome;
    try {
      outcome = await this.drive(execution, identity, writer, context);
    } catch (error) {
      if (!(error instanceof Outcome)) {
        throw error;
      }
      outcome = error;
    }
    await this.finish(execution, identity, writer, outcome);
    return { state: outcome.state };
  }

  /** Settles an execution whose outcome can no longer be determined. */
  public async abandon(execution: Execution): Promise<void> {
    const identity = { companyId: execution.companyId, userId: execution.userId, roles: [] };
    const writer = new ChatWriter(
      this.unique,
      identity,
      execution.chatId,
      execution.assistantMessageId,
    );
    await this.finish(
      execution,
      identity,
      writer,
      new Outcome(
        'unknown',
        execution.remoteTaskId ? MESSAGES.unreachable : MESSAGES.unknown,
        'recovery-exhausted',
      ),
    );
  }

  private async drive(
    execution: Execution,
    identity: RequestIdentity,
    writer: ChatWriter,
    context: TaskContext,
  ): Promise<Outcome> {
    const { client, card } = await this.connect(execution, identity);
    const deadlineAt = execution.deadlineAt ?? new Date(Date.now() + this.config.streamTimeoutMs);
    if (!execution.deadlineAt) {
      await this.executions.transition(identity, execution.id, execution.state as ExecutionState, {
        deadlineAt,
      });
    }
    const turn = new RemoteTurn();
    let recordedTaskId = execution.remoteTaskId;
    let recordedContextId: string | undefined;
    const onUpdate = async (): Promise<void> => {
      if (turn.taskId && turn.taskId !== recordedTaskId) {
        await this.executions.transition(identity, execution.id, 'working', {
          remoteTaskId: turn.taskId,
        });
        recordedTaskId = turn.taskId;
      }
      if (turn.contextId && turn.contextId !== recordedContextId) {
        await this.executions.saveRemoteContext(
          identity.companyId,
          execution.connectionId,
          execution.chatId,
          turn.contextId,
        );
        recordedContextId = turn.contextId;
      }
      await writer.progress(renderParts(turn.answerParts(), this.renderFile));
    };
    const streaming = card.capabilities?.streaming === true;
    try {
      await this.watch(execution, identity, deadlineAt, context, async (signal) => {
        if (!execution.remoteTaskId) {
          await this.send(execution, identity, client, streaming, turn, onUpdate, signal);
        } else {
          turn.taskId = execution.remoteTaskId;
          await this.resume(client, streaming, turn, onUpdate, signal);
        }
        await this.poll(client, turn, onUpdate, signal);
      });
    } catch (error) {
      if (error instanceof Interrupted) {
        return this.interrupt(client, turn, error.kind);
      }
      throw peerFailure(error) ?? error;
    }
    return this.settle(turn);
  }

  private async connect(
    execution: Execution,
    identity: RequestIdentity,
  ): Promise<{ client: Client; card: AgentCard }> {
    const connection = await this.connections.find(identity.companyId, execution.connectionId);
    if (!connection || connection.disabledAt || !connection.agentCardSnapshot) {
      throw new Outcome('failed', MESSAGES.connection, 'connection');
    }
    const card = connection.agentCardSnapshot as unknown as AgentCard;
    if (!acceptsText(card)) {
      throw new Outcome('failed', MESSAGES.unsupportedInput, 'input-modes');
    }
    let fetchImpl: typeof fetch;
    try {
      fetchImpl = (await this.credentials.remoteFetch(identity, {
        assistantId: execution.assistantId,
        connectionId: execution.connectionId,
        executionId: execution.id,
      })) as typeof fetch;
    } catch (error) {
      if (error instanceof ForbiddenException || error instanceof NotFoundException) {
        throw new Outcome('failed', MESSAGES.forbidden, 'forbidden');
      }
      throw error;
    }
    const client = await new ClientFactory({
      transports: [new JsonRpcTransportFactory({ fetchImpl })],
      preferredTransports: ['JSONRPC'],
      clientConfig: { polling: true, acceptedOutputModes: OUTPUT_MODES },
    }).createFromAgentCard(card);
    if (client.protocolVersion !== '1.0') {
      throw new Outcome('failed', MESSAGES.version, 'version');
    }
    return { client, card };
  }

  /** Sends the turn at most once: a crash after `sending` is reported, never re-sent. */
  private async send(
    execution: Execution,
    identity: RequestIdentity,
    client: Client,
    streaming: boolean,
    turn: RemoteTurn,
    onUpdate: () => Promise<void>,
    signal: AbortSignal,
  ): Promise<void> {
    if (execution.state === 'sending') {
      throw new Outcome('unknown', MESSAGES.unknown, 'ambiguous-send');
    }
    const message = await this.remoteMessage(execution, identity);
    await this.executions.transition(identity, execution.id, 'sending');
    const request = {
      tenant: '',
      message,
      configuration: {
        acceptedOutputModes: OUTPUT_MODES,
        taskPushNotificationConfig: undefined,
        returnImmediately: true,
      },
      metadata: undefined,
    };
    try {
      if (streaming) {
        for await (const event of client.sendMessageStream(request, { signal })) {
          turn.apply(event);
          await onUpdate();
          if (turn.isSettled) {
            break;
          }
        }
      } else {
        turn.apply(await client.sendMessage(request, { signal }));
        await onUpdate();
      }
    } catch (error) {
      if (turn.taskId || signal.aborted || peerFailure(error)) {
        throw error;
      }
      throw new Outcome('unknown', MESSAGES.unknown, 'send-failed');
    }
    if (!turn.taskId && !turn.isSettled) {
      throw new Outcome('unknown', MESSAGES.unknown, 'no-task');
    }
  }

  private async resume(
    client: Client,
    streaming: boolean,
    turn: RemoteTurn,
    onUpdate: () => Promise<void>,
    signal: AbortSignal,
  ): Promise<void> {
    const id = turn.taskId ?? '';
    if (streaming) {
      try {
        for await (const event of client.resubscribeTask({ tenant: '', id }, { signal })) {
          turn.apply(event);
          await onUpdate();
          if (turn.isSettled) {
            return;
          }
        }
        return;
      } catch (error) {
        if (signal.aborted) {
          throw error;
        }
      }
    }
    turn.apply(await client.getTask({ tenant: '', id }, { signal }));
    await onUpdate();
  }

  private async poll(
    client: Client,
    turn: RemoteTurn,
    onUpdate: () => Promise<void>,
    signal: AbortSignal,
  ): Promise<void> {
    let interval = 1_000;
    let failures = 0;
    while (!turn.isSettled) {
      await delay(interval, undefined, { signal });
      interval = Math.min(interval * 1.5, MAX_POLL_INTERVAL_MS);
      try {
        turn.apply(await client.getTask({ tenant: '', id: turn.taskId ?? '' }, { signal }));
        failures = 0;
      } catch (error) {
        if (signal.aborted || error instanceof TaskNotFoundError) {
          throw error;
        }
        failures += 1;
        if (failures >= MAX_CONSECUTIVE_POLL_FAILURES) {
          throw new Outcome('unknown', MESSAGES.unreachable, 'unreachable');
        }
        continue;
      }
      await onUpdate();
    }
  }

  /**
   * Runs `work` while heartbeating the absurd lease and watching for a user cancel or the
   * deadline; either aborts the remote call and surfaces as {@link Interrupted}.
   */
  private async watch(
    execution: Execution,
    identity: RequestIdentity,
    deadlineAt: Date,
    context: TaskContext,
    work: (signal: AbortSignal) => Promise<void>,
  ): Promise<void> {
    const controller = new AbortController();
    let interruption: Interrupted | undefined;
    let ticks = 0;
    const check = async (): Promise<void> => {
      await context.heartbeat();
      const current = await this.executions.findOwned(identity, execution.id);
      // Events can be missed while no replica is subscribed; core state is authoritative.
      if (!current.cancelRequestedAt && ticks++ % 5 === 0 && (await this.stoppedInCore(current))) {
        await this.executions.requestCancel(identity.companyId, execution.id);
        interruption = new Interrupted('cancel');
      } else if (current.cancelRequestedAt) {
        interruption = new Interrupted('cancel');
      } else if (Date.now() >= deadlineAt.getTime()) {
        interruption = new Interrupted('deadline');
      }
      if (interruption) {
        controller.abort(interruption);
      }
    };
    await check();
    const timer = setInterval(() => {
      check().catch((error: unknown) =>
        this.logger.warn({ msg: 'execution watch failed', executionId: execution.id, err: error }),
      );
    }, WATCH_INTERVAL_MS);
    try {
      await work(controller.signal);
    } catch (error) {
      throw interruption ?? error;
    } finally {
      clearInterval(timer);
    }
    if (interruption) {
      throw interruption;
    }
  }

  private async stoppedInCore(execution: Execution): Promise<boolean> {
    const identity = { companyId: execution.companyId, userId: execution.userId, roles: [] };
    const messages = [{ chatId: execution.chatId, messageId: execution.assistantMessageId }];
    const parent = parentTurn.safeParse(execution.correlation);
    if (parent.success) {
      messages.push({ chatId: parent.data.parentChatId, messageId: parent.data.parentMessageId });
    }
    for (const { chatId, messageId } of messages) {
      const message = abortState.safeParse(
        await this.unique.getMessage(identity, chatId, messageId),
      );
      if (message.success && message.data.userAbortedAt) {
        return true;
      }
    }
    return false;
  }

  /** Cancels remotely and reports only what the remote agent confirms. */
  private async interrupt(
    client: Client,
    turn: RemoteTurn,
    kind: Interrupted['kind'],
  ): Promise<Outcome> {
    const text = kind === 'cancel' ? MESSAGES.canceled : MESSAGES.timeout;
    const localState: OutcomeState = kind === 'cancel' ? 'canceled' : 'failed';
    if (!turn.taskId) {
      return new Outcome(turn.isSettled ? localState : 'unknown', text, `${kind}:no-remote-task`);
    }
    if (turn.isSettled) {
      return this.settle(turn);
    }
    try {
      turn.apply(await client.cancelTask({ tenant: '', id: turn.taskId, metadata: undefined }));
    } catch (error) {
      const reason =
        error instanceof TaskNotCancelableError
          ? 'not-cancelable'
          : error instanceof UnsupportedOperationError
            ? 'cancel-unsupported'
            : 'cancel-failed';
      return new Outcome('unknown', text, `${kind}:${reason}`);
    }
    if (turn.phase === 'canceled') {
      return new Outcome(localState, text, kind);
    }
    return turn.isSettled ? this.settle(turn) : new Outcome('unknown', text, `${kind}:pending`);
  }

  private settle(turn: RemoteTurn): Outcome {
    const answer = renderParts(turn.answerParts(), this.renderFile);
    switch (turn.phase) {
      case 'completed':
        return new Outcome('completed', answer || MESSAGES.empty);
      case 'canceled':
        return new Outcome('canceled', answer || MESSAGES.canceled, 'remote-canceled');
      case 'input-required':
      case 'auth-required':
        return new Outcome('failed', MESSAGES.interaction, turn.phase);
      default: {
        const detail = turn.statusText();
        return new Outcome(
          'failed',
          detail ? `${MESSAGES.failed}\n\n> ${detail.replaceAll('\n', '\n> ')}` : MESSAGES.failed,
          `remote-${turn.phase}`,
        );
      }
    }
  }

  private async finish(
    execution: Execution,
    identity: RequestIdentity,
    writer: ChatWriter,
    outcome: Outcome,
  ): Promise<void> {
    try {
      if (!(await writer.isClosed())) {
        if (outcome.state === 'completed') {
          await writer.complete(outcome.text);
        } else {
          await writer.fail(outcome.text);
        }
      }
    } catch (error) {
      if (!(error instanceof UniqueInternalError) || error.retryable) {
        throw error;
      }
      this.logger.warn({ msg: 'assistant message is gone', executionId: execution.id });
    }
    await this.executions.transition(identity, execution.id, outcome.state, {
      lastError: outcome.reason ?? null,
    });
    this.logger.log({
      action: 'execution.finish',
      companyId: identity.companyId,
      executionId: execution.id,
      state: outcome.state,
      reason: outcome.reason,
    });
  }

  private async remoteMessage(execution: Execution, identity: RequestIdentity): Promise<Message> {
    const turn = userMessage.parse(
      await this.unique.getMessage(identity, execution.chatId, execution.userMessageId),
    );
    if (!turn.text?.trim()) {
      throw new Outcome('failed', MESSAGES.unsupported, 'empty-turn');
    }
    const remoteContext = await this.executions.findRemoteContext(
      identity.companyId,
      execution.connectionId,
      execution.chatId,
    );
    return {
      // Deterministic, so a peer that deduplicates by messageId recognises a retried send.
      messageId: execution.id,
      contextId: remoteContext?.remoteContextId ?? '',
      taskId: '',
      role: Role.ROLE_USER,
      parts: [textPart(turn.text)],
      metadata: undefined,
      extensions: [],
      referenceTaskIds: [],
    };
  }

  private readonly renderFile = (part: Part): string =>
    `_The external agent returned a file (${part.filename || part.mediaType || 'unnamed'}) that cannot be displayed yet._`;
}
