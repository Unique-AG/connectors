/**
 * Deterministic A2A 1.0 peer for local development, contract tests and the TCK smoke run.
 * The first word of the user message selects the behaviour (see README in this folder).
 *
 *   FIXTURE_PORT=9571 FIXTURE_STREAMING=true node test/fixtures/fixture-agent.ts
 */
import { createServer } from 'node:http';
import type { AddressInfo } from 'node:net';
import { setTimeout as delay } from 'node:timers/promises';
import {
  type AgentCard,
  type Artifact,
  type Message,
  type Part,
  Role,
  type Task,
  TaskState,
} from '@a2a-js/sdk';
import {
  AgentEvent,
  type AgentExecutor,
  DefaultRequestHandler,
  type ExecutionEventBus,
  InMemoryPushNotificationStore,
  InMemoryTaskStore,
  type RequestContext,
} from '@a2a-js/sdk/server';
import { agentCardHandler, jsonRpcHandler, UserBuilder } from '@a2a-js/sdk/server/express';
import express from 'express';

export interface FixtureAgentOptions {
  port?: number;
  streaming?: boolean;
  push?: boolean;
  token?: string;
}

export interface FixtureAgent {
  url: string;
  cardUrl: string;
  received: unknown[];
  close: () => Promise<void>;
}

function text(value: string): Part {
  return {
    content: { $case: 'text', value },
    metadata: undefined,
    filename: '',
    mediaType: 'text/plain',
  };
}

function agentMessage(parts: Part[], taskId = '', contextId = ''): Message {
  return {
    messageId: crypto.randomUUID(),
    contextId,
    taskId,
    role: Role.ROLE_AGENT,
    parts,
    metadata: undefined,
    extensions: [],
    referenceTaskIds: [],
  };
}

function status(
  bus: ExecutionEventBus,
  context: RequestContext,
  state: TaskState,
  message?: Message,
): void {
  bus.publish(
    AgentEvent.statusUpdate({
      taskId: context.taskId,
      contextId: context.contextId,
      status: { state, message, timestamp: new Date().toISOString() },
      metadata: undefined,
    }),
  );
}

function artifact(
  bus: ExecutionEventBus,
  context: RequestContext,
  value: Artifact,
  append = false,
  lastChunk = true,
): void {
  bus.publish(
    AgentEvent.artifactUpdate({
      taskId: context.taskId,
      contextId: context.contextId,
      artifact: value,
      append,
      lastChunk,
      metadata: undefined,
    }),
  );
}

function answer(parts: Part[], artifactId = 'answer'): Artifact {
  return {
    artifactId,
    name: 'Answer',
    description: '',
    parts,
    metadata: undefined,
    extensions: [],
  };
}

function textOf(message: Message): string {
  return message.parts
    .map((part) => {
      if (part.content?.$case === 'text') {
        return part.content.value;
      }
      return part.content?.$case === 'data' ? JSON.stringify(part.content.value) : '';
    })
    .join('')
    .trim();
}

export async function startFixtureAgent(options: FixtureAgentOptions = {}): Promise<FixtureAgent> {
  const streaming = options.streaming ?? true;
  const push = options.push ?? false;
  const token = options.token;
  const server = createServer();
  await new Promise<void>((resolve) => server.listen(options.port ?? 0, '127.0.0.1', resolve));
  const baseUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  const canceled = new Set<string>();

  const executor: AgentExecutor = {
    async execute(context, bus) {
      const input = textOf(context.userMessage);
      const command = input.split(/\s+/)[0]?.toLowerCase() ?? '';
      if (command === 'message') {
        bus.publish(
          AgentEvent.message(agentMessage([text(`Direct reply: ${input}`)], '', context.contextId)),
        );
        bus.finished();
        return;
      }
      const existing = context.task;
      const task: Task = existing ?? {
        id: context.taskId,
        contextId: context.contextId,
        status: {
          state: TaskState.TASK_STATE_SUBMITTED,
          message: undefined,
          timestamp: new Date().toISOString(),
        },
        artifacts: [],
        history: [context.userMessage],
        metadata: undefined,
      };
      bus.publish(AgentEvent.task(task));
      status(bus, context, TaskState.TASK_STATE_WORKING);
      const awaited = existing?.status?.state;
      if (awaited === TaskState.TASK_STATE_INPUT_REQUIRED) {
        artifact(bus, context, answer([text(`Thanks, you answered: ${input}`)]));
        status(bus, context, TaskState.TASK_STATE_COMPLETED);
      } else if (command === 'fail') {
        status(
          bus,
          context,
          TaskState.TASK_STATE_FAILED,
          agentMessage([text('Fixture failure requested.')], context.taskId, context.contextId),
        );
      } else if (command === 'reject') {
        status(
          bus,
          context,
          TaskState.TASK_STATE_REJECTED,
          agentMessage([text('Fixture rejected the task.')], context.taskId, context.contextId),
        );
      } else if (command === 'input') {
        status(
          bus,
          context,
          TaskState.TASK_STATE_INPUT_REQUIRED,
          agentMessage(
            [
              text('Which city should I use?'),
              {
                content: {
                  $case: 'data',
                  value: {
                    type: 'object',
                    properties: { city: { type: 'string', title: 'City' } },
                    required: ['city'],
                  },
                },
                metadata: undefined,
                filename: '',
                mediaType: 'application/json',
              },
            ],
            context.taskId,
            context.contextId,
          ),
        );
      } else if (command === 'auth') {
        status(
          bus,
          context,
          TaskState.TASK_STATE_AUTH_REQUIRED,
          agentMessage(
            [text('Sign in at https://auth.example/login to continue.')],
            context.taskId,
            context.contextId,
          ),
        );
      } else if (command === 'json') {
        artifact(
          bus,
          context,
          answer([
            text('Here is the structured result:'),
            {
              content: { $case: 'data', value: { temperature: 21, unit: 'C' } },
              metadata: undefined,
              filename: '',
              mediaType: 'application/json',
            },
          ]),
        );
        status(bus, context, TaskState.TASK_STATE_COMPLETED);
      } else if (command === 'file') {
        artifact(
          bus,
          context,
          answer([
            text('Here is your report.'),
            {
              content: { $case: 'raw', value: Buffer.from('Fixture report\n') },
              metadata: undefined,
              filename: 'report.txt',
              mediaType: 'text/plain',
            },
            {
              content: { $case: 'url', value: `${baseUrl}/files/chart.csv` },
              metadata: undefined,
              filename: 'chart.csv',
              mediaType: 'text/csv',
            },
          ]),
        );
        status(bus, context, TaskState.TASK_STATE_COMPLETED);
      } else if (command === 'slow') {
        for (let step = 1; step <= 30; step += 1) {
          if (canceled.has(context.taskId)) {
            status(bus, context, TaskState.TASK_STATE_CANCELED);
            bus.finished();
            return;
          }
          artifact(bus, context, answer([text(`Step ${step} done. `)]), step > 1, step === 30);
          await delay(1_000);
        }
        status(bus, context, TaskState.TASK_STATE_COMPLETED);
      } else {
        const words = `Echo: ${input}`.split(' ');
        for (const [index, word] of words.entries()) {
          artifact(
            bus,
            context,
            answer([text(index ? ` ${word}` : word)]),
            index > 0,
            index === words.length - 1,
          );
          await delay(80);
        }
        status(bus, context, TaskState.TASK_STATE_COMPLETED);
      }
      bus.finished();
    },
    async cancelTask(taskId, bus) {
      canceled.add(taskId);
      bus.publish(
        AgentEvent.statusUpdate({
          taskId,
          contextId: '',
          status: {
            state: TaskState.TASK_STATE_CANCELED,
            message: undefined,
            timestamp: new Date().toISOString(),
          },
          metadata: undefined,
        }),
      );
    },
  };

  const card: AgentCard = {
    name: streaming ? 'Fixture agent (streaming)' : 'Fixture agent (polling)',
    description: 'Deterministic A2A 1.0 test peer.',
    supportedInterfaces: [
      { url: `${baseUrl}/a2a`, protocolBinding: 'JSONRPC', protocolVersion: '1.0', tenant: '' },
    ],
    provider: { organization: 'Unique fixtures', url: baseUrl },
    version: '1.0.0',
    capabilities: { streaming, pushNotifications: push, extendedAgentCard: false, extensions: [] },
    securitySchemes: token
      ? {
          bearer: {
            scheme: {
              $case: 'httpAuthSecurityScheme',
              value: { description: '', scheme: 'Bearer', bearerFormat: '' },
            },
          },
        }
      : {},
    securityRequirements: token ? [{ schemes: { bearer: { list: [] } } }] : [],
    defaultInputModes: ['text/plain'],
    defaultOutputModes: ['text/plain', 'application/json'],
    skills: [
      {
        id: 'echo',
        name: 'Echo',
        description: 'Echoes the message.',
        tags: [],
        examples: [],
        inputModes: [],
        outputModes: [],
        securityRequirements: [],
      },
    ],
    signatures: [],
  };

  const requestHandler = new DefaultRequestHandler(
    card,
    new InMemoryTaskStore(),
    executor,
    undefined,
    push ? new InMemoryPushNotificationStore() : undefined,
  );
  // Records push notifications this fixture receives, e.g. from the gateway's inbound tasks.
  const received: unknown[] = [];
  const app = express();
  app.use('/.well-known/agent-card.json', agentCardHandler({ agentCardProvider: requestHandler }));
  app.post('/webhook-sink', express.json({ type: '*/*' }), (request, response) => {
    received.push({
      headers: { token: request.headers['x-a2a-notification-token'] },
      body: request.body,
    });
    response.status(204).end();
  });
  app.get('/webhook-sink', (_request, response) => {
    response.json(received);
  });
  app.get('/files/chart.csv', (_request, response) => {
    response.type('text/csv').send('city,temperature\nZurich,21\n');
  });
  app.use('/a2a', (request, response, next) => {
    if (token && request.headers.authorization !== `Bearer ${token}`) {
      response.status(401).json({ error: 'unauthorized' });
      return;
    }
    next();
  });
  app.use('/a2a', jsonRpcHandler({ requestHandler, userBuilder: UserBuilder.noAuthentication }));
  server.on('request', app);
  return {
    url: baseUrl,
    cardUrl: `${baseUrl}/.well-known/agent-card.json`,
    received,
    close: () => new Promise<void>((resolve) => server.close(() => resolve())),
  };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const agent = await startFixtureAgent({
    port: Number(process.env.FIXTURE_PORT ?? 9571),
    streaming: process.env.FIXTURE_STREAMING !== 'false',
    push: process.env.FIXTURE_PUSH === 'true',
    token: process.env.FIXTURE_TOKEN,
  });
  console.log(`fixture agent on ${agent.url}`);
}
