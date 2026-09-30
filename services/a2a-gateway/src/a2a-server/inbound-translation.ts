import {
  type Artifact,
  type Message,
  type Part,
  Role,
  type Task,
  TaskState,
  type TaskStatus,
} from '@a2a-js/sdk';
import type { NativeMessage, RunOutcome } from './native-run-observer.js';

export const TERMINAL_TASK_STATES = [
  TaskState.TASK_STATE_COMPLETED,
  TaskState.TASK_STATE_FAILED,
  TaskState.TASK_STATE_CANCELED,
  TaskState.TASK_STATE_REJECTED,
];

const FAILURE_TEXT = 'The space could not complete this request.';

function textPart(value: string): Part {
  return {
    content: { $case: 'text', value },
    metadata: undefined,
    filename: '',
    mediaType: 'text/plain',
  };
}

function dataPart(value: unknown): Part {
  return {
    content: { $case: 'data', value },
    metadata: undefined,
    filename: '',
    mediaType: 'application/json',
  };
}

function agentMessage(task: Pick<Task, 'id' | 'contextId'>, id: string, parts: Part[]): Message {
  return {
    messageId: `${id}-${task.id}`,
    contextId: task.contextId,
    taskId: task.id,
    role: Role.ROLE_AGENT,
    parts,
    metadata: undefined,
    extensions: [],
    referenceTaskIds: [],
  };
}

export function taskStatus(state: TaskState, message?: Message): TaskStatus {
  return { state, message, timestamp: new Date().toISOString() };
}

export function failedStatus(task: Pick<Task, 'id' | 'contextId'>, reason?: string): TaskStatus {
  return taskStatus(
    TaskState.TASK_STATE_FAILED,
    agentMessage(task, 'failure', [textPart(reason ?? FAILURE_TEXT)]),
  );
}

/** The answer artifact; replaced (not appended) on every update so clients converge. */
export function textArtifact(taskId: string, text: string): Artifact {
  return {
    artifactId: `response-${taskId}`,
    name: 'Response',
    description: '',
    parts: [textPart(text)],
    metadata: undefined,
    extensions: [],
  };
}

/** Citations as a versioned structured-data convention; internal ids are never exposed. */
function referencesArtifact(taskId: string, message: NativeMessage): Artifact | undefined {
  const references = (message.references ?? []).map((reference) => ({
    number: reference.sequenceNumber ?? undefined,
    name: reference.name,
    ...(reference.url && /^https?:\/\//.test(reference.url) ? { url: reference.url } : {}),
  }));
  if (!references.length) {
    return undefined;
  }
  return {
    artifactId: `references-${taskId}`,
    name: 'References',
    description: 'Sources cited in the response',
    parts: [dataPart({ references })],
    metadata: { kind: 'unique.references', version: 1 },
    extensions: [],
  };
}

const CONTENT_URL = /unique:\/\/content\/([A-Za-z0-9_]+)/g;

export type FileUrl = (contentId: string) => string;

export function fileUrlFor(publicBaseUrl: URL, publicationId: string, taskId: string): FileUrl {
  return (contentId) => {
    const url = new URL(
      `a2a/agents/${encodeURIComponent(publicationId)}/files/${encodeURIComponent(contentId)}`,
      publicBaseUrl.toString().endsWith('/') ? publicBaseUrl : `${publicBaseUrl.toString()}/`,
    );
    url.searchParams.set('taskId', taskId);
    return url.toString();
  };
}

/**
 * Files the answer links (generated or cited chat content) as URL parts pointing at the
 * gateway's authorized download route; core content ids never leave as bare references.
 */
function filesArtifact(taskId: string, message: NativeMessage, fileUrl: FileUrl) {
  const names = new Map<string, string>();
  for (const reference of message.references ?? []) {
    const id = /^unique:\/\/content\/([A-Za-z0-9_]+)$/.exec(reference.url ?? '')?.[1];
    if (id) {
      names.set(id, reference.name);
    }
  }
  for (const match of (message.text ?? '').matchAll(CONTENT_URL)) {
    if (match[1] && !names.has(match[1])) {
      names.set(match[1], match[1]);
    }
  }
  if (!names.size) {
    return undefined;
  }
  return {
    artifactId: `files-${taskId}`,
    name: 'Files',
    description: 'Files referenced by the response',
    parts: [...names].map(([id, name]) => ({
      content: { $case: 'url' as const, value: fileUrl(id) },
      metadata: undefined,
      filename: name,
      mediaType: '',
    })),
    metadata: undefined,
    extensions: [],
  };
}

export function outcomeArtifacts(
  taskId: string,
  outcome: RunOutcome,
  fileUrl: FileUrl,
): Artifact[] {
  if (outcome.kind !== 'completed') {
    return [];
  }
  return [
    textArtifact(taskId, outcome.message.text ?? ''),
    referencesArtifact(taskId, outcome.message),
    filesArtifact(taskId, outcome.message, fileUrl),
  ].filter((artifact): artifact is Artifact => artifact !== undefined);
}

/** The artifact file URL a task exposes for a content id, if any. */
export function taskFileUrl(task: Task, contentId: string): string | undefined {
  return task.artifacts
    .flatMap((artifact) => artifact.parts)
    .map((part) => (part.content?.$case === 'url' ? part.content.value : ''))
    .find((url) => url.includes(`/files/${encodeURIComponent(contentId)}?`));
}

export function outcomeStatus(
  task: Pick<Task, 'id' | 'contextId'>,
  outcome: RunOutcome,
): TaskStatus {
  switch (outcome.kind) {
    case 'completed':
      return taskStatus(TaskState.TASK_STATE_COMPLETED);
    case 'canceled':
      return taskStatus(TaskState.TASK_STATE_CANCELED);
    case 'failed':
      return failedStatus(task);
    case 'elicitation': {
      const { elicitation } = outcome;
      const parts = [
        ...(elicitation.message ? [textPart(elicitation.message)] : []),
        elicitation.mode === 'FORM'
          ? dataPart(elicitation.schema ?? {})
          : textPart(elicitation.url ?? ''),
      ];
      return taskStatus(
        elicitation.mode === 'FORM'
          ? TaskState.TASK_STATE_INPUT_REQUIRED
          : TaskState.TASK_STATE_AUTH_REQUIRED,
        agentMessage(task, `elicitation-${elicitation.id}`, parts),
      );
    }
  }
}

export function isTerminal(task: Task): boolean {
  return task.status !== undefined && TERMINAL_TASK_STATES.includes(task.status.state);
}
