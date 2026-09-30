import type { SendMessageRequest } from '@a2a-js/sdk';
import { ClientFactory, JsonRpcTransportFactory } from '@a2a-js/sdk/client';
import {
  DefaultExecutionEventBusManager,
  DefaultRequestHandler,
  JsonRpcTransportHandler,
  ServerCallContext,
} from '@a2a-js/sdk/server';
import { Injectable } from '@nestjs/common';
import type { RequestIdentity } from '../auth/identity.guard.js';
import { ResourceAuthorizationService } from '../auth/resource-authorization.service.js';
import { InboundAdmissionService } from './inbound-admission.service.js';
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

class AdmittingRequestHandler extends DefaultRequestHandler {
  public constructor(
    private readonly admission: InboundAdmissionService,
    ...handler: ConstructorParameters<typeof DefaultRequestHandler>
  ) {
    super(...handler);
  }

  public override async sendMessage(params: SendMessageRequest, context: ServerCallContext) {
    return super.sendMessage(await this.admission.admit(params, context), context);
  }

  public override async *sendMessageStream(params: SendMessageRequest, context: ServerCallContext) {
    yield* super.sendMessageStream(await this.admission.admit(params, context), context);
  }
}

@Injectable()
export class A2aSdkService {
  public readonly clientFactory = new ClientFactory({
    transports: [new JsonRpcTransportFactory()],
    preferredTransports: ['JSONRPC'],
  });
  private readonly buses = new DefaultExecutionEventBusManager();

  public constructor(
    private readonly admission: InboundAdmissionService,
    private readonly authorization: ResourceAuthorizationService,
    private readonly executor: InboundAgentExecutor,
    private readonly publications: PublicationService,
    private readonly taskStore: PgTaskStore,
  ) {}

  public async handleJsonRpc(call: JsonRpcCall) {
    const card = await this.publications.getTenantAgentCard(
      call.identity.companyId,
      call.publicationId,
    );
    const requestHandler = new AdmittingRequestHandler(
      this.admission,
      card,
      this.taskStore,
      this.executor,
      this.buses,
      undefined,
      undefined,
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
