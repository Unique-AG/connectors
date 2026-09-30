/**
 * Minimal, deterministic stand-in for the Unique core services the gateway calls (node-chat,
 * scope-management and ingestion GraphQL), so the official A2A TCK can exercise the inbound
 * surface in CI without LLMs. One native space `assistant_tck` answers every turn with
 * "Hello from TCK" after a short delay.
 *
 * Permissions follow the forwarded identity headers: in company `tck-company`, `tck-user` manages
 * the space, `tck-colleague` may use it and anyone else has no access. `assistant_external` is an
 * A2A-provider space. `state` toggles the rollout flag for gate tests.
 *
 *   STUB_CORE_PORT=9590 node test/fixtures/stub-core.ts
 */
import { randomUUID } from 'node:crypto';
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';

export const TCK_ASSISTANT_ID = 'assistant_tck';
export const EXTERNAL_ASSISTANT_ID = 'assistant_external';
export const TCK_COMPANY = 'tck-company';
export const TCK_MANAGER = 'tck-user';
export const TCK_COLLEAGUE = 'tck-colleague';
const ANSWER = 'Hello from TCK';
const ANSWER_DELAY_MS = Number(process.env.STUB_CORE_ANSWER_DELAY_MS ?? 200);

interface StoredMessage {
  id: string;
  chatId: string;
  role: 'USER' | 'ASSISTANT';
  text: string;
  previousMessageId?: string;
  completedAt: string | null;
  stoppedStreamingAt: string | null;
  userAbortedAt: string | null;
}

interface Variables {
  assistantId?: string;
  chatId?: string;
  messageId?: string;
  input: { text: string };
}

const FORBIDDEN = Symbol('forbidden');

interface Identity {
  companyId: string;
  userId: string;
}

function body(request: IncomingMessage): Promise<string> {
  return new Promise((resolve) => {
    const chunks: Buffer[] = [];
    request.on('data', (chunk: Buffer) => chunks.push(chunk));
    request.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
  });
}

function send(response: ServerResponse, status: number, payload: unknown): void {
  response.writeHead(status, { 'content-type': 'application/json' }).end(JSON.stringify(payload));
}

export async function startStubCore(port = 0) {
  // Unique across runs: gateway state in a reused database references these ids.
  const id = (prefix: string) => `${prefix}_${randomUUID()}`;
  const messages = new Map<string, StoredMessage>();
  const state = { a2aEnabled: true, answerDelayMs: ANSWER_DELAY_MS };
  const assistants = new Map([
    [
      TCK_ASSISTANT_ID,
      {
        id: TCK_ASSISTANT_ID,
        name: 'TCK space',
        executionProvider: 'NATIVE',
        a2aConnectionId: null,
      },
    ],
    [
      EXTERNAL_ASSISTANT_ID,
      {
        id: EXTERNAL_ASSISTANT_ID,
        name: 'External space',
        executionProvider: 'A2A',
        a2aConnectionId: null,
      },
    ],
  ]);
  const inCompany = (identity: Identity) => identity.companyId === TCK_COMPANY;
  const isManager = (identity: Identity) => inCompany(identity) && identity.userId === TCK_MANAGER;
  const isMember = (identity: Identity) =>
    isManager(identity) || (inCompany(identity) && identity.userId === TCK_COLLEAGUE);

  const operations: Record<string, (variables: Variables, identity: Identity) => unknown> = {
    A2aCapabilities: () => ({
      a2aCapabilities: {
        configured: true,
        enabled: state.a2aEnabled,
        available: true,
        retryable: false,
      },
    }),
    A2aPermissions: (_variables, identity) => ({
      getUserPermissions: { uiPermissions: { canAccessSpaceManagement: isManager(identity) } },
    }),
    A2aAssistant: ({ assistantId }, identity) =>
      isMember(identity)
        ? { assistantByUser: assistants.get(assistantId ?? '') ?? null }
        : FORBIDDEN,
    A2aManagedAssistant: ({ assistantId }, identity) =>
      isManager(identity)
        ? { assistantByCompany: assistants.get(assistantId ?? '') ?? null }
        : FORBIDDEN,
    A2aChatCreate: () => ({ chatCreate: { id: id('chat') } }),
    A2aMessageCreate: ({ chatId, input }) => {
      const chat = chatId ?? id('chat');
      const user: StoredMessage = {
        id: id('msg'),
        chatId: chat,
        role: 'USER',
        text: input.text,
        completedAt: null,
        stoppedStreamingAt: null,
        userAbortedAt: null,
      };
      const reply: StoredMessage = {
        id: id('msg'),
        chatId: chat,
        role: 'ASSISTANT',
        text: '',
        previousMessageId: user.id,
        completedAt: null,
        stoppedStreamingAt: null,
        userAbortedAt: null,
      };
      messages.set(user.id, user);
      messages.set(reply.id, reply);
      setTimeout(() => {
        if (!reply.stoppedStreamingAt) {
          reply.text = ANSWER;
          reply.completedAt = new Date().toISOString();
        }
      }, state.answerDelayMs);
      return { messageCreate: { id: user.id, chatId: chat, messages: [] } };
    },
    A2aMessage: ({ messageId }) => ({
      message:
        messageId && messages.has(messageId)
          ? { ...messages.get(messageId), references: [] }
          : null,
    }),
    A2aMessageReplies: ({ messageId }) => ({
      message: {
        id: messageId,
        messages: [...messages.values()]
          .filter((m) => m.previousMessageId === messageId)
          .map((m) => ({ id: m.id })),
      },
    }),
    A2aTurn: () => ({ messages: [] }),
    A2aChatElicitations: () => ({ elicitationsByChat: [] }),
    A2aMessageElicitations: () => ({ elicitationsByMessage: [] }),
    A2aMessageStop: ({ messageId }) => {
      const message = messageId ? messages.get(messageId) : undefined;
      if (message && !message.completedAt) {
        message.stoppedStreamingAt = new Date().toISOString();
        message.userAbortedAt = message.stoppedStreamingAt;
      }
      return {
        messageStopStreaming: message
          ? { id: message.id, stoppedStreamingAt: message.stoppedStreamingAt }
          : null,
      };
    },
  };

  const server = createServer(async (request, response) => {
    if (request.method !== 'POST' || !request.url?.startsWith('/graphql')) {
      send(response, 404, { message: 'not found' });
      return;
    }
    const { query, variables } = JSON.parse(await body(request)) as {
      query: string;
      variables?: Variables;
    };
    const operation = /(?:query|mutation)\s+(\w+)/.exec(query)?.[1] ?? '';
    const handler = operations[operation];
    if (!handler) {
      send(response, 200, {
        errors: [{ message: `unsupported operation ${operation}`, extensions: { code: '400' } }],
        data: null,
      });
      return;
    }
    const identity = {
      companyId: String(request.headers['x-company-id'] ?? ''),
      userId: String(request.headers['x-user-id'] ?? ''),
    };
    const data = handler(variables ?? { input: { text: '' } }, identity);
    send(
      response,
      200,
      data === FORBIDDEN
        ? { errors: [{ message: 'forbidden', extensions: { code: 'FORBIDDEN' } }], data: null }
        : { data },
    );
  });
  await new Promise<void>((resolve) => server.listen(port, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  return { url, state, close: () => new Promise<void>((resolve) => server.close(() => resolve())) };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const core = await startStubCore(Number(process.env.STUB_CORE_PORT ?? 9590));
  console.log(`stub core on ${core.url}`);
}
