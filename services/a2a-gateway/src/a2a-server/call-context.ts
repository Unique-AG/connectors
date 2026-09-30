import type { Message, Task } from '@a2a-js/sdk';
import { TaskState } from '@a2a-js/sdk';
import { ContentTypeNotSupportedError, RequestMalformedError } from '@a2a-js/sdk/errors';
import type { ServerCallContext } from '@a2a-js/sdk/server';
import { NotFoundException } from '@nestjs/common';
import type { RequestIdentity } from '../auth/identity.guard.js';
import { isAllowedMediaType, normalizeMediaType, safeFilename } from '../bridge/file-policy.js';

export function callIdentity(context: ServerCallContext): RequestIdentity {
  const userId = context.user?.isAuthenticated ? context.user.userName : undefined;
  const roles = context.state.get('roles');
  if (!context.tenant || !userId) {
    throw new NotFoundException('publication not found');
  }
  return {
    companyId: context.tenant,
    userId,
    roles: Array.isArray(roles)
      ? roles.filter((role): role is string => typeof role === 'string')
      : [],
  };
}

export function callPublicationId(context: ServerCallContext): string {
  const value = context.state.get('publicationId');
  if (typeof value !== 'string' || !value) {
    throw new NotFoundException('publication not found');
  }
  return value;
}

export interface InboundFile {
  bytes: Buffer;
  filename: string;
  mimeType: string;
}

export interface InboundContent {
  text: string;
  files: InboundFile[];
}

/**
 * Text and data become the native message text (data as fenced JSON); inline file bytes are
 * uploaded to the chat. URL references are refused: the gateway does not fetch client URLs.
 */
export function messageContent(message: Message, maxFileBytes: number): InboundContent {
  let text = '';
  const files: InboundFile[] = [];
  for (const [index, part] of message.parts.entries()) {
    const content = part.content;
    if (content?.$case === 'text') {
      text += content.value;
    } else if (content?.$case === 'data') {
      text += `\n\n\`\`\`json\n${JSON.stringify(content.value, null, 2)}\n\`\`\``;
    } else if (content?.$case === 'raw') {
      const mimeType = normalizeMediaType(part.mediaType);
      if (!isAllowedMediaType(mimeType)) {
        throw new ContentTypeNotSupportedError(`files of type ${mimeType} are not supported`);
      }
      if (content.value.byteLength > maxFileBytes) {
        throw new RequestMalformedError('a file exceeds the size limit');
      }
      files.push({
        bytes: Buffer.from(content.value),
        filename: safeFilename(part.filename, `file-${index + 1}`),
        mimeType,
      });
    } else {
      throw new ContentTypeNotSupportedError(
        'only text, data and inline file parts are supported; send file bytes instead of URLs',
      );
    }
  }
  const trimmed = text.trim();
  if (!trimmed && !files.length) {
    throw new RequestMalformedError('message content is required');
  }
  return {
    text:
      trimmed ||
      `Please process the attached file(s): ${files.map((file) => file.filename).join(', ')}`,
    files,
  };
}

/** Text-only content, e.g. an answer to an elicitation. */
export function messageText(message: Message): string {
  return messageContent(message, 0).text;
}

export function awaitsInput(task: Task): boolean {
  return (
    task.status?.state === TaskState.TASK_STATE_INPUT_REQUIRED ||
    task.status?.state === TaskState.TASK_STATE_AUTH_REQUIRED
  );
}
