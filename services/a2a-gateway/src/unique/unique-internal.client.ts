import { Inject, Injectable } from '@nestjs/common';
import { z } from 'zod';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';
import { UniqueInternalError } from './unique-internal.error.js';

export interface EffectiveIdentity {
  companyId: string;
  userId: string;
  roles: string[];
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
      `query A2aAssistant($assistantId: String!) { assistantByUser(assistantId: $assistantId) { id name executionProvider a2aConnectionId } }`,
      { assistantId },
      'assistantByUser',
    );
  }

  public verifySpaceManagement(identity: EffectiveIdentity, assistantId: string): Promise<unknown> {
    return this.graphql(
      this.config.uniqueChatUrl,
      identity,
      `query A2aManagedAssistant($assistantId: String!) { assistantByCompany(assistantId: $assistantId) { id name executionProvider a2aConnectionId } }`,
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
    assistantId: string,
    chatId: string | undefined,
    text: string,
    selectedUploadedFileIds?: string[],
  ): Promise<unknown> {
    return this.graphql(
      this.config.uniqueChatUrl,
      identity,
      `mutation A2aMessageCreate($assistantId: String, $chatId: String, $input: MessageCreateInput!, $fileIds: [String!]) {
        messageCreate(assistantId: $assistantId, chatId: $chatId, input: $input, selectedUploadedFileIds: $fileIds) {
          id chatId messages { id }
        }
      }`,
      {
        assistantId,
        chatId,
        input: { role: 'USER', text },
        ...(selectedUploadedFileIds?.length ? { fileIds: selectedUploadedFileIds } : {}),
      },
      'messageCreate',
    );
  }

  public createChat(identity: EffectiveIdentity, assistantId: string): Promise<unknown> {
    return this.graphql(
      this.config.uniqueChatUrl,
      identity,
      `mutation A2aChatCreate($assistantId: String) { chatCreate(assistantId: $assistantId) { id } }`,
      { assistantId },
      'chatCreate',
    );
  }

  public getMessage(
    identity: EffectiveIdentity,
    chatId: string,
    messageId: string,
  ): Promise<unknown> {
    return this.graphql(
      this.config.uniqueChatUrl,
      identity,
      `query A2aMessage($chatId: String!, $messageId: String!) {
        message(chatId: $chatId, messageId: $messageId) {
          id text completedAt stoppedStreamingAt userAbortedAt
          references { name url sequenceNumber sourceId source }
        }
      }`,
      { chatId, messageId },
      'message',
    );
  }

  /** All assistant segments answering one user turn (multi-segment spaces). */
  public getTurnSegments(
    identity: EffectiveIdentity,
    chatId: string,
    userMessageId: string,
  ): Promise<unknown> {
    return this.graphql(
      this.config.uniqueChatUrl,
      identity,
      `query A2aTurn($chatId: String!, $where: MessageWhereInput) {
        messages(chatId: $chatId, where: $where) {
          id text segmentKind segmentIndex completedAt stoppedStreamingAt userAbortedAt
          references { name url sequenceNumber sourceId source }
        }
      }`,
      {
        chatId,
        where: { responseTurnId: { equals: userMessageId }, role: { equals: 'ASSISTANT' } },
      },
      'messages',
    );
  }

  public getChatElicitations(identity: EffectiveIdentity, chatId: string): Promise<unknown> {
    return this.graphql(
      this.config.uniqueChatUrl,
      identity,
      `query A2aChatElicitations($chatId: String!) {
        elicitationsByChat(chatId: $chatId) { id userId messageId mode status message schema url expiresAt }
      }`,
      { chatId },
      'elicitationsByChat',
    );
  }

  /** Replies to a message; the assistant shell of a user turn is its first reply. */
  public getMessageReplies(
    identity: EffectiveIdentity,
    chatId: string,
    messageId: string,
  ): Promise<unknown> {
    return this.graphql(
      this.config.uniqueChatUrl,
      identity,
      `query A2aMessageReplies($chatId: String!, $messageId: String!) {
        message(chatId: $chatId, messageId: $messageId) { id messages { id } }
      }`,
      { chatId, messageId },
      'message',
    );
  }

  public stopMessage(
    identity: EffectiveIdentity,
    chatId: string,
    messageId: string,
  ): Promise<unknown> {
    return this.graphql(
      this.config.uniqueChatUrl,
      identity,
      `mutation A2aMessageStop($chatId: String!, $messageId: String!) {
        messageStopStreaming(chatId: $chatId, messageId: $messageId) { id stoppedStreamingAt }
      }`,
      { chatId, messageId },
      'messageStopStreaming',
    );
  }

  /** Pushes an unpersisted progress update of a streaming answer to the chat UI. */
  public publishMessageProgress(
    identity: EffectiveIdentity,
    chatId: string,
    messageId: string,
    input: { text: string },
  ): Promise<unknown> {
    return this.graphql(
      this.config.uniqueChatUrl,
      identity,
      `mutation A2aMessageProgress($chatId: String!, $messageId: String!, $input: MessageCreateEventInput) {
        messageCreateEvent(chatId: $chatId, messageId: $messageId, input: $input) { id }
      }`,
      { chatId, messageId, input },
      'messageCreateEvent',
    );
  }

  public updateAssistantMessage(
    identity: EffectiveIdentity,
    chatId: string,
    messageId: string,
    input: Record<string, unknown>,
  ): Promise<unknown> {
    return this.graphql(
      this.config.uniqueChatUrl,
      identity,
      `mutation A2aMessageUpdate($chatId: String!, $messageId: String!, $input: MessagePublicUpdateInput!) {
        messagePublicUpdate(chatId: $chatId, messageId: $messageId, input: $input) { id completedAt stoppedStreamingAt }
      }`,
      { chatId, messageId, input },
      'messagePublicUpdate',
    );
  }

  public getMessageElicitations(identity: EffectiveIdentity, messageId: string): Promise<unknown> {
    return this.graphql(
      this.config.uniqueChatUrl,
      identity,
      `query A2aMessageElicitations($messageId: String!) {
        elicitationsByMessage(messageId: $messageId) { id userId mode status message schema url expiresAt responseContent }
      }`,
      { messageId },
      'elicitationsByMessage',
    );
  }

  public getElicitation(identity: EffectiveIdentity, elicitationId: string): Promise<unknown> {
    return this.graphql(
      this.config.uniqueChatUrl,
      identity,
      `query A2aElicitation($id: String!) {
        elicitation(id: $id) { id userId mode status message schema url expiresAt responseContent }
      }`,
      { id: elicitationId },
      'elicitation',
    );
  }

  public respondToElicitation(
    identity: EffectiveIdentity,
    elicitationId: string,
    action: 'ACCEPT' | 'DECLINE' | 'CANCEL',
    content?: Record<string, unknown>,
  ): Promise<unknown> {
    return this.graphql(
      this.config.uniqueChatUrl,
      identity,
      `mutation A2aElicitationRespond($input: ElicitationResponseInput!) {
        respondToElicitation(input: $input) { success message }
      }`,
      { input: { elicitationId, action, ...(content ? { content } : {}) } },
      'respondToElicitation',
    );
  }

  public createElicitation(
    identity: EffectiveIdentity,
    input: Record<string, unknown>,
  ): Promise<unknown> {
    return this.graphql(
      this.config.uniqueChatUrl,
      identity,
      `mutation A2aElicitationCreate($input: ElicitationCreateInput!) { createElicitation(input: $input) { id expiresAt } }`,
      { input },
      'createElicitation',
    );
  }

  /** Creates or finalises chat-owned content; the first call returns the blob write URL. */
  public upsertChatContent(
    identity: EffectiveIdentity,
    chatId: string,
    input: Record<string, unknown>,
    fileUrl?: string,
  ): Promise<unknown> {
    return this.graphql(
      this.config.uniqueIngestionUrl,
      identity,
      `mutation A2aContentUpsert($chatId: String!, $input: ContentCreateInput!, $fileUrl: String) {
        contentUpsertByChat(chatId: $chatId, input: $input, fileUrl: $fileUrl) {
          id ownerId ownerType internallyStoredAt versioningEnabled currentVersion writeUrl readUrl
        }
      }`,
      { chatId, input, ...(fileUrl ? { fileUrl } : {}) },
      'contentUpsertByChat',
    );
  }

  /** Streams chat content under the user's own content permissions, bounded to `maxBytes`. */
  public async downloadContent(
    identity: EffectiveIdentity,
    contentId: string,
    chatId: string,
    maxBytes: number,
  ): Promise<{ bytes: Buffer; mimeType: string; filename: string }> {
    const url = new URL(
      `v1/content/${encodeURIComponent(contentId)}/file`,
      this.config.uniqueIngestionUrl.toString().endsWith('/')
        ? this.config.uniqueIngestionUrl
        : `${this.config.uniqueIngestionUrl.toString()}/`,
    );
    url.searchParams.set('chatId', chatId);
    let response: Response;
    try {
      response = await fetch(url, {
        headers: { 'x-company-id': identity.companyId, 'x-user-id': identity.userId },
        signal: AbortSignal.timeout(this.config.streamTimeoutMs),
        redirect: 'error',
      });
    } catch {
      throw new UniqueInternalError('Unique content download failed', 'UNAVAILABLE', true);
    }
    if (!response.ok) {
      const code = errorCode(response.status);
      throw new UniqueInternalError(`content download returned ${response.status}`, code, false);
    }
    const length = Number(response.headers.get('content-length') ?? 0);
    if (length > maxBytes) {
      throw new UniqueInternalError('content exceeds the size limit', 'TOO_LARGE', false);
    }
    const bytes = Buffer.from(await response.arrayBuffer());
    if (bytes.byteLength > maxBytes) {
      throw new UniqueInternalError('content exceeds the size limit', 'TOO_LARGE', false);
    }
    const disposition = response.headers.get('content-disposition') ?? '';
    const filename =
      decodeURIComponent(/filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1] ?? '') ||
      /filename="?([^";]+)"?/i.exec(disposition)?.[1] ||
      contentId;
    return {
      bytes,
      mimeType: response.headers.get('content-type')?.split(';')[0] ?? 'application/octet-stream',
      filename,
    };
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
