import type { Message, Task } from '@a2a-js/sdk';
import { TaskState } from '@a2a-js/sdk';
import { ContentTypeNotSupportedError, RequestMalformedError } from '@a2a-js/sdk/errors';
import type { ServerCallContext } from '@a2a-js/sdk/server';
import { NotFoundException } from '@nestjs/common';
import type { RequestIdentity } from '../auth/identity.guard.js';

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

export function messageText(message: Message): string {
  const values = message.parts.map((part) => {
    if (part.content?.$case === 'text') {
      return part.content.value;
    }
    if (part.content?.$case === 'data') {
      return `\n\n\`\`\`json\n${JSON.stringify(part.content.value, null, 2)}\n\`\`\``;
    }
    throw new ContentTypeNotSupportedError('only text and data message parts are supported');
  });
  const text = values.join('').trim();
  if (!text) {
    throw new RequestMalformedError('message content is required');
  }
  return text;
}

export function awaitsInput(task: Task): boolean {
  return (
    task.status?.state === TaskState.TASK_STATE_INPUT_REQUIRED ||
    task.status?.state === TaskState.TASK_STATE_AUTH_REQUIRED
  );
}
