/**
 * Contract tests of the outbound runner against real A2A 1.0 peers over HTTP (the fixture agents),
 * using the official SDK client exactly as in production. Only Unique core and the database are
 * replaced by in-memory fakes.
 */
import type { AgentCard } from '@a2a-js/sdk';
import type { TaskContext } from 'absurd-sdk';
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import type { ChatFilesService } from '../../src/bridge/chat-files.service.js';
import { loadConfig } from '../../src/config/config.js';
import { parseAgentCard } from '../../src/credentials/agent-card.js';
import type { CredentialProviderService } from '../../src/credentials/credential-provider.service.js';
import { EgressService } from '../../src/credentials/egress.service.js';
import type { ConnectionRepository } from '../../src/drizzle/connection.repository.js';
import {
  ACTIVE_EXECUTION_STATES,
  type Execution,
  type ExecutionRepository,
} from '../../src/drizzle/execution.repository.js';
import type { AuditLog } from '../../src/observability/audit-log.service.js';
import type { GatewayMetrics } from '../../src/observability/gateway-metrics.service.js';
import { CallbackWakeups } from '../../src/outbound/callback-wakeups.service.js';
import { OutboundRunner } from '../../src/outbound/outbound-runner.service.js';
import type { UniqueInternalClient } from '../../src/unique/unique-internal.client.js';
import type { WorkflowService } from '../../src/workflow/workflow.service.js';
import { type FixtureAgent, startFixtureAgent } from '../fixtures/fixture-agent.js';

const config = loadConfig({
  NODE_ENV: 'test',
  DATABASE_URL: 'postgresql://localhost/a2a',
  AMQP_URL: 'amqp://localhost',
  PUBLIC_BASE_URL: 'https://gateway.example/',
  ZITADEL_ISSUER: 'https://identity.example/',
  UNIQUE_CHAT_URL: 'http://node-chat/',
  UNIQUE_SCOPE_MANAGEMENT_URL: 'http://scope-management/',
  UNIQUE_INGESTION_URL: 'http://node-ingestion/',
  ENCRYPTION_KEY: '22'.repeat(32),
  EGRESS_ALLOWED_HOSTS: '127.0.0.1',
  EGRESS_ALLOW_INSECURE: 'true',
  STREAM_TIMEOUT_MS: '30000',
});

const context = {
  heartbeat: vi.fn(async () => undefined),
  step: async <T>(_name: string, fn: () => Promise<T>) => fn(),
} as unknown as TaskContext;

interface Scenario {
  execution: Execution;
  final?: Record<string, unknown>;
  progress: string[];
  uploads: { filename: string; mimeType: string; bytes: number }[];
  elicitations: Record<string, unknown>[];
}

function harness(card: AgentCard, userText: string) {
  const egress = new EgressService(config);
  const execution: Execution = {
    id: `exec_${Math.random().toString(36).slice(2)}`,
    companyId: 'company-1',
    userId: 'user-1',
    connectionId: 'conn-1',
    assistantId: 'space-1',
    chatId: 'chat-1',
    userMessageId: 'user-msg',
    assistantMessageId: 'assistant-msg',
    remoteTaskId: null,
    state: 'submitted',
    correlation: {},
    elicitationId: null,
    deadlineAt: null,
    lastError: null,
    cancelRequestedAt: null,
    finishedAt: null,
    workflowTaskId: null,
    recoveries: 0,
    bytesIn: 0,
    bytesOut: 0,
    expiresAt: new Date(Date.now() + 86_400_000),
    createdAt: new Date(),
    updatedAt: new Date(),
  };
  const scenario: Scenario = { execution, progress: [], uploads: [], elicitations: [] };
  let elicitation: { status: string; responseContent?: unknown } = { status: 'PENDING' };
  const executions = {
    findOwned: vi.fn(async () => ({ ...scenario.execution })),
    transition: vi.fn(async (_principal: unknown, _id: string, state: string, patch = {}) => {
      if (!ACTIVE_EXECUTION_STATES.includes(scenario.execution.state)) {
        return undefined;
      }
      scenario.execution = { ...scenario.execution, ...patch, state };
      return scenario.execution;
    }),
    requestCancel: vi.fn(async () => {
      scenario.execution = { ...scenario.execution, cancelRequestedAt: new Date() };
      return true;
    }),
    saveRemoteContext: vi.fn(),
    findRemoteContext: vi.fn(async () => undefined),
    addBytes: vi.fn(),
  };
  const unique = {
    getMessage: vi.fn(async (_identity: unknown, _chatId: string, messageId: string) =>
      messageId === 'user-msg'
        ? { id: messageId, text: userText }
        : { id: messageId, completedAt: null, stoppedStreamingAt: null, userAbortedAt: null },
    ),
    publishMessageProgress: vi.fn(
      async (_i: unknown, _c: string, _m: string, input: { text: string }) => {
        scenario.progress.push(input.text);
      },
    ),
    updateAssistantMessage: vi.fn(
      async (_i: unknown, _c: string, _m: string, input: Record<string, unknown>) => {
        if (input.completedAt || input.stoppedStreamingAt) {
          scenario.final = input;
        } else if (typeof input.text === 'string') {
          scenario.progress.push(input.text);
        }
      },
    ),
    createElicitation: vi.fn(async (_identity: unknown, input: Record<string, unknown>) => {
      scenario.elicitations.push(input);
      return { id: `elicit-${scenario.elicitations.length}` };
    }),
    getElicitation: vi.fn(async () => ({
      ...elicitation,
      schema: scenario.elicitations.at(-1)?.schema,
    })),
  };
  const runner = new OutboundRunner(
    {
      find: vi.fn(async () => ({ id: 'conn-1', disabledAt: null, agentCardSnapshot: card })),
    } as unknown as ConnectionRepository,
    {
      remoteFetch: vi.fn(
        async () =>
          (input: string | URL, init: RequestInit = {}) =>
            egress.stream(input, init, 10_000_000),
      ),
    } as unknown as CredentialProviderService,
    executions as unknown as ExecutionRepository,
    unique as unknown as UniqueInternalClient,
    { register: vi.fn() } as unknown as WorkflowService,
    {
      upload: vi.fn(
        async (
          _identity: unknown,
          _chatId: string,
          file: { filename: string; mimeType: string; bytes: Buffer },
        ) => {
          scenario.uploads.push({
            filename: file.filename,
            mimeType: file.mimeType,
            bytes: file.bytes.byteLength,
          });
          return `cont_${scenario.uploads.length}`;
        },
      ),
    } as unknown as ChatFilesService,
    egress,
    new CallbackWakeups(config),
    { bytesExchanged: vi.fn(), runFinished: vi.fn() } as unknown as GatewayMetrics,
    { record: vi.fn() } as unknown as AuditLog,
    config,
  );
  const run = () =>
    runner.run(
      { executionId: execution.id, companyId: execution.companyId, userId: execution.userId },
      context,
    );
  return {
    scenario,
    run,
    executions,
    answer: (value: typeof elicitation) => {
      elicitation = value;
    },
  };
}

async function card(agent: FixtureAgent): Promise<AgentCard> {
  return parseAgentCard(await (await fetch(agent.cardUrl)).json());
}

describe('outbound runner against A2A 1.0 peers', () => {
  let streamingAgent: FixtureAgent;
  let pollingAgent: FixtureAgent;
  let streamingCard: AgentCard;
  let pollingCard: AgentCard;

  beforeAll(async () => {
    streamingAgent = await startFixtureAgent({ streaming: true });
    pollingAgent = await startFixtureAgent({ streaming: false });
    streamingCard = await card(streamingAgent);
    pollingCard = await card(pollingAgent);
  });
  afterAll(async () => {
    await streamingAgent.close();
    await pollingAgent.close();
  });

  it.each([
    ['a streaming task-based peer', () => streamingCard],
    ['a polling task-based peer', () => pollingCard],
  ])('completes a turn with %s and streams progress', async (_peer, cardOf) => {
    const { scenario, run } = harness(cardOf(), 'hello there peer');
    await expect(run()).resolves.toEqual({ state: 'completed' });
    expect(scenario.final).toMatchObject({
      text: 'Echo: hello there peer',
      completedAt: expect.any(String),
    });
    expect(scenario.execution.remoteTaskId).toBeTruthy();
  });

  it('accepts a direct Message reply from a message-only exchange', async () => {
    const { scenario, run } = harness(pollingCard, 'message ping');
    await run();
    expect(scenario.final).toMatchObject({ text: 'Direct reply: message ping' });
    expect(scenario.execution.state).toBe('completed');
  });

  it('reports a remote failure with the remote reason as plain quoted text', async () => {
    const { scenario, run } = harness(streamingCard, 'fail now');
    await expect(run()).resolves.toEqual({ state: 'failed' });
    expect(scenario.final?.text).toContain('Fixture failure requested.');
    expect(scenario.final).toMatchObject({ stoppedStreamingAt: expect.any(String) });
  });

  it('renders structured data as JSON and stores remote files as chat references', async () => {
    const data = harness(streamingCard, 'json please');
    await data.run();
    expect(data.scenario.final?.text).toContain('"temperature": 21');

    const files = harness(streamingCard, 'file please');
    await files.run();
    expect(files.scenario.uploads).toEqual([
      { filename: 'report.txt', mimeType: 'text/plain', bytes: 15 },
      { filename: 'chart.csv', mimeType: 'text/csv', bytes: 27 },
    ]);
    expect(files.scenario.final?.references).toHaveLength(2);
  });

  it('asks the human for input and answers the same remote task', async () => {
    const { scenario, run, answer } = harness(streamingCard, 'input needed');
    const running = run();
    await vi.waitFor(() => expect(scenario.elicitations).toHaveLength(1), { timeout: 10_000 });
    expect(scenario.elicitations[0]).toMatchObject({
      mode: 'FORM',
      message: 'Which city should I use?',
      schema: { properties: { city: { type: 'string' } } },
    });
    answer({ status: 'ACCEPTED', responseContent: { city: 'Zurich' } });
    await expect(running).resolves.toEqual({ state: 'completed' });
    expect(scenario.final?.text).toBe('Thanks, you answered: {"city":"Zurich"}');
  });

  it('cancels the remote task when the human declines', async () => {
    const { scenario, run, answer } = harness(streamingCard, 'input needed');
    const running = run();
    await vi.waitFor(() => expect(scenario.elicitations).toHaveLength(1), { timeout: 10_000 });
    answer({ status: 'DECLINED' });
    await expect(running).resolves.toEqual({ state: 'canceled' });
  });

  it('fails auth-required explicitly instead of hanging', async () => {
    const { scenario, run } = harness(streamingCard, 'auth please');
    await expect(run()).resolves.toEqual({ state: 'failed' });
    expect(scenario.final?.text).toMatch(/requires additional authorization/);
  });

  it('cancels remotely on a user stop and reports it only once the peer confirms', async () => {
    const { scenario, run, executions } = harness(streamingCard, 'slow work');
    const running = run();
    await vi.waitFor(() => expect(scenario.progress.length).toBeGreaterThan(0), {
      timeout: 10_000,
    });
    await executions.requestCancel();
    await expect(running).resolves.toEqual({ state: 'canceled' });
    expect(scenario.execution.lastError).toBe('cancel');
  });

  it('never re-sends a turn whose send outcome is unknown after a crash', async () => {
    const { scenario, run } = harness(streamingCard, 'hello again');
    scenario.execution = { ...scenario.execution, state: 'sending' };
    await expect(run()).resolves.toEqual({ state: 'unknown' });
    expect(scenario.final?.text).toMatch(/outcome is unknown/);
  });

  it('refuses a peer that does not accept text input before sending', async () => {
    const { scenario, run } = harness(
      { ...streamingCard, defaultInputModes: ['application/json'] },
      'hello',
    );
    await expect(run()).resolves.toEqual({ state: 'failed' });
    expect(scenario.final?.text).toMatch(/does not accept text/);
  });
});
