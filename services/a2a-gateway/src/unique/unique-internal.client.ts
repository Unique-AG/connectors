import { Inject, Injectable } from '@nestjs/common';
import { z } from 'zod';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';

export interface EffectiveIdentity {
  companyId: string;
  userId: string;
  roles: string[];
}

export class UniqueInternalError extends Error {
  public constructor(
    message: string,
    public readonly code:
      | 'UNAUTHORIZED'
      | 'NOT_FOUND'
      | 'CONFLICT'
      | 'UNAVAILABLE'
      | 'INVALID_RESPONSE',
    public readonly retryable: boolean,
  ) {
    super(message);
  }
}

const graphQlResponse = z.object({
  data: z.record(z.string(), z.unknown()).optional(),
  errors: z
    .array(
      z.object({ message: z.string(), extensions: z.record(z.string(), z.unknown()).optional() }),
    )
    .optional(),
});

function endpoint(base: URL): URL {
  return new URL('graphql', base.toString().endsWith('/') ? base : `${base.toString()}/`);
}

function errorCode(status: number): UniqueInternalError['code'] {
  if (status === 401 || status === 403) {
    return 'UNAUTHORIZED';
  }
  if (status === 404) {
    return 'NOT_FOUND';
  }
  if (status === 409) {
    return 'CONFLICT';
  }
  return 'UNAVAILABLE';
}

@Injectable()
export class UniqueInternalClient {
  public constructor(@Inject(GATEWAY_CONFIG) private readonly config: GatewayConfig) {}

  public getAssistant(identity: EffectiveIdentity, assistantId: string): Promise<unknown> {
    return this.graphql(
      this.config.uniqueChatUrl,
      identity,
      `query A2aAssistant($assistantId: String!) { assistantByUser(assistantId: $assistantId) { id name } }`,
      { assistantId },
      'assistantByUser',
    );
  }

  public verifySpaceManagement(identity: EffectiveIdentity, assistantId: string): Promise<unknown> {
    return this.graphql(
      this.config.uniqueChatUrl,
      identity,
      `query A2aManagedAssistant($assistantId: String!) { assistantByCompany(assistantId: $assistantId) { id name } }`,
      { assistantId },
      'assistantByCompany',
    );
  }

  public getCapabilities(identity: EffectiveIdentity): Promise<unknown> {
    return this.graphql(
      this.config.uniqueChatUrl,
      identity,
      `query A2aCapabilities { a2aCapabilities { configured enabled available retryable reason } }`,
      {},
      'a2aCapabilities',
    );
  }

  public getPermissions(identity: EffectiveIdentity): Promise<unknown> {
    return this.graphql(
      this.config.uniqueScopeManagementUrl,
      identity,
      `query A2aPermissions { getUserPermissions { uiPermissions { canAccessSpaceManagement } } }`,
      {},
      'getUserPermissions',
    );
  }

  public createMessage(
    identity: EffectiveIdentity,
    input: Record<string, unknown>,
  ): Promise<unknown> {
    return this.graphql(
      this.config.uniqueChatUrl,
      identity,
      `mutation A2aMessageCreate($input: MessageCreateInput!) { messageCreate(input: $input) { id chatId } }`,
      { input },
      'messageCreate',
    );
  }

  public getMessage(identity: EffectiveIdentity, messageId: string): Promise<unknown> {
    return this.graphql(
      this.config.uniqueChatUrl,
      identity,
      `query A2aMessage($messageId: ID!) { message(messageId: $messageId) { id completedAt stoppedStreamingAt segments } }`,
      { messageId },
      'message',
    );
  }

  public stopMessage(identity: EffectiveIdentity, messageId: string): Promise<unknown> {
    return this.graphql(
      this.config.uniqueChatUrl,
      identity,
      `mutation A2aMessageStop($messageId: ID!) { messageStopStreaming(messageId: $messageId) { id stoppedStreamingAt } }`,
      { messageId },
      'messageStopStreaming',
    );
  }

  public getPendingElicitation(identity: EffectiveIdentity, messageId: string): Promise<unknown> {
    return this.graphql(
      this.config.uniqueChatUrl,
      identity,
      `query A2aPendingElicitation($messageId: ID!) { elicitationGetPending(messageId: $messageId) { id mode schema url } }`,
      { messageId },
      'elicitationGetPending',
    );
  }

  public respondToElicitation(
    identity: EffectiveIdentity,
    elicitationId: string,
    action: string,
    content?: unknown,
  ): Promise<unknown> {
    return this.graphql(
      this.config.uniqueChatUrl,
      identity,
      `mutation A2aElicitationRespond($input: ElicitationRespondInput!) { elicitationRespond(input: $input) { id status } }`,
      { input: { elicitationId, action, content } },
      'elicitationRespond',
    );
  }

  public createElicitation(
    identity: EffectiveIdentity,
    input: Record<string, unknown>,
  ): Promise<unknown> {
    return this.graphql(
      this.config.uniqueChatUrl,
      identity,
      `mutation A2aElicitationCreate($input: ElicitationCreateInput!) { elicitationCreate(input: $input) { id } }`,
      { input },
      'elicitationCreate',
    );
  }

  public updateAssistantMessage(
    identity: EffectiveIdentity,
    input: Record<string, unknown>,
  ): Promise<unknown> {
    return this.graphql(
      this.config.uniqueChatUrl,
      identity,
      `mutation A2aMessageUpdate($input: MessagePublicUpdateInput!) { messagePublicUpdate(input: $input) { id completedAt } }`,
      { input },
      'messagePublicUpdate',
    );
  }

  public upsertChatContent(
    identity: EffectiveIdentity,
    input: Record<string, unknown>,
  ): Promise<unknown> {
    return this.graphql(
      this.config.uniqueIngestionUrl,
      identity,
      `mutation A2aContentUpsert($input: ContentUpsertByChatInput!) { contentUpsertByChat(input: $input) { id } }`,
      { input },
      'contentUpsertByChat',
    );
  }

  private async graphql(
    baseUrl: URL,
    identity: EffectiveIdentity,
    query: string,
    variables: Record<string, unknown>,
    resultKey: string,
  ): Promise<unknown> {
    let response: Response;
    try {
      response = await fetch(endpoint(baseUrl), {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          'x-company-id': identity.companyId,
          'x-user-id': identity.userId,
        },
        body: JSON.stringify({ query, variables }),
        signal: AbortSignal.timeout(this.config.dependencyTimeoutMs),
        redirect: 'error',
      });
    } catch {
      throw new UniqueInternalError('Unique internal request failed', 'UNAVAILABLE', true);
    }
    if (!response.ok) {
      const code = errorCode(response.status);
      throw new UniqueInternalError(
        `Unique internal request returned ${response.status}`,
        code,
        code === 'UNAVAILABLE',
      );
    }
    const parsed = graphQlResponse.safeParse(await response.json());
    if (!parsed.success) {
      throw new UniqueInternalError(
        'Unique internal response is invalid',
        'INVALID_RESPONSE',
        false,
      );
    }
    const firstError = parsed.data.errors?.[0];
    if (firstError) {
      const extensionCode = firstError.extensions?.code;
      const code =
        extensionCode === 'FORBIDDEN' || extensionCode === 'UNAUTHENTICATED'
          ? 'UNAUTHORIZED'
          : extensionCode === 'NOT_FOUND'
            ? 'NOT_FOUND'
            : extensionCode === 'CONFLICT'
              ? 'CONFLICT'
              : 'INVALID_RESPONSE';
      throw new UniqueInternalError('Unique internal operation failed', code, false);
    }
    const result = parsed.data.data?.[resultKey];
    if (result === undefined || result === null) {
      throw new UniqueInternalError(`${resultKey} was not returned`, 'NOT_FOUND', false);
    }
    return result;
  }
}
