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

export function outcomeArtifacts(taskId: string, outcome: RunOutcome): Artifact[] {
  if (outcome.kind !== 'completed') {
    return [];
  }
  const artifacts = [textArtifact(taskId, outcome.message.text ?? '')];
  const references = referencesArtifact(taskId, outcome.message);
  return references ? [...artifacts, references] : artifacts;
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
