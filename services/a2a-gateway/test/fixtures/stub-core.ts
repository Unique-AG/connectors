/**
 * Minimal, deterministic stand-in for the Unique core services the gateway calls (node-chat,
 * scope-management and ingestion GraphQL), so the official A2A TCK can exercise the inbound
 * surface in CI without LLMs. One native space `assistant_tck` answers every turn with
 * "Hello from TCK" after a short delay.
 *
 *   STUB_CORE_PORT=9590 node test/fixtures/stub-core.ts
 */
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';

export const TCK_ASSISTANT_ID = 'assistant_tck';
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
  let sequence = 0;
  const id = (prefix: string) => `${prefix}_${++sequence}`;
  const messages = new Map<string, StoredMessage>();
  const assistant = {
    id: TCK_ASSISTANT_ID,
    name: 'TCK space',
    executionProvider: 'NATIVE',
    a2aConnectionId: null,
  };

  const operations: Record<string, (variables: Variables) => unknown> = {
    A2aCapabilities: () => ({
      a2aCapabilities: { configured: true, enabled: true, available: true, retryable: false },
    }),
    A2aPermissions: () => ({
      getUserPermissions: { uiPermissions: { canAccessSpaceManagement: true } },
    }),
    A2aAssistant: ({ assistantId }) => ({
      assistantByUser: assistantId === TCK_ASSISTANT_ID ? assistant : null,
    }),
    A2aManagedAssistant: ({ assistantId }) => ({
      assistantByCompany: assistantId === TCK_ASSISTANT_ID ? assistant : null,
    }),
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
      }, ANSWER_DELAY_MS);
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
    send(response, 200, { data: handler(variables ?? { input: { text: '' } }) });
  });
  await new Promise<void>((resolve) => server.listen(port, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  return { url, close: () => new Promise<void>((resolve) => server.close(() => resolve())) };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const core = await startStubCore(Number(process.env.STUB_CORE_PORT ?? 9590));
  console.log(`stub core on ${core.url}`);
}
