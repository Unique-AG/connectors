import { ClientFactory, JsonRpcTransportFactory } from '@a2a-js/sdk/client';
import {
  DefaultExecutionEventBusManager,
  DefaultRequestHandler,
  JsonRpcTransportHandler,
  ServerCallContext,
} from '@a2a-js/sdk/server';
import { Injectable } from '@nestjs/common';
import { typeid } from 'typeid-js';
import type { RequestIdentity } from '../auth/identity.guard.js';
import { InboundAgentExecutor } from './inbound-agent.executor.js';
import { PgTaskStore } from './pg-task.store.js';
import { PublicationService } from './publication.service.js';

interface JsonRpcCall {
  body: unknown;
  headers: Record<string, string | string[] | undefined>;
  identity: RequestIdentity;
  publicationId: string;
  requestedVersion?: string;
}

function withServerIds(body: unknown): unknown {
  if (typeof body !== 'object' || body === null) {
    return body;
  }
  const request = structuredClone(body) as Record<string, unknown>;
  if (!['SendMessage', 'SendStreamingMessage'].includes(String(request.method))) {
    return request;
  }
  const params = request.params;
  if (typeof params !== 'object' || params === null) {
    return request;
  }
  const message = Reflect.get(params, 'message');
  if (typeof message !== 'object' || message === null) {
    return request;
  }
  if (!Reflect.get(message, 'contextId')) {
    Reflect.set(message, 'contextId', typeid('ctx').toString());
  }
  if (!Reflect.get(message, 'taskId')) {
    Reflect.set(message, 'taskId', typeid('task').toString());
  }
  return request;
}

@Injectable()
export class A2aSdkService {
  public readonly clientFactory = new ClientFactory({
    transports: [new JsonRpcTransportFactory()],
    preferredTransports: ['JSONRPC'],
  });
  private readonly buses = new DefaultExecutionEventBusManager();

  public constructor(
    private readonly executor: InboundAgentExecutor,
    private readonly publications: PublicationService,
    private readonly taskStore: PgTaskStore,
  ) {}

  public async handleJsonRpc(call: JsonRpcCall) {
    const card = await this.publications.getAgentCard(call.publicationId);
    const requestHandler = new DefaultRequestHandler(
      card,
      this.taskStore,
      this.executor,
      this.buses,
      undefined,
      undefined,
      async () => {
        await this.publications.catalog(call.identity);
        return this.publications.getAgentCard(call.publicationId);
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
    const body = withServerIds(call.body);
    if (typeof body !== 'string' && (typeof body !== 'object' || body === null)) {
      return new JsonRpcTransportHandler(requestHandler).handle({}, context);
    }
    return new JsonRpcTransportHandler(requestHandler).handle(
      body as string | Record<string, unknown>,
      context,
    );
  }
}
