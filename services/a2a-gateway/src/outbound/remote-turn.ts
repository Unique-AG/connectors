import {
  type Artifact,
  type Message,
  type Part,
  type StreamResponse,
  type Task,
  TaskState,
  type TaskStatus,
} from '@a2a-js/sdk';

export type TurnPhase =
  | 'active'
  | 'input-required'
  | 'auth-required'
  | 'completed'
  | 'failed'
  | 'canceled'
  | 'rejected';

const PHASES: Partial<Record<TaskState, TurnPhase>> = {
  [TaskState.TASK_STATE_COMPLETED]: 'completed',
  [TaskState.TASK_STATE_FAILED]: 'failed',
  [TaskState.TASK_STATE_CANCELED]: 'canceled',
  [TaskState.TASK_STATE_REJECTED]: 'rejected',
  [TaskState.TASK_STATE_INPUT_REQUIRED]: 'input-required',
  [TaskState.TASK_STATE_AUTH_REQUIRED]: 'auth-required',
};

export const TERMINAL_PHASES: TurnPhase[] = ['completed', 'failed', 'canceled', 'rejected'];

function isTask(result: Message | Task | StreamResponse): result is Task {
  return 'status' in result && 'artifacts' in result;
}

function isMessage(result: Message | Task | StreamResponse): result is Message {
  return 'messageId' in result && 'role' in result;
}

/**
 * Folds everything a remote agent returns for one turn (a direct Message, Task snapshots, or
 * status/artifact stream events) into one view. Remote content is data only: it is rendered for
 * the user, never interpreted.
 */
export class RemoteTurn {
  public taskId: string | undefined;
  public contextId: string | undefined;
  private state: TaskState = TaskState.TASK_STATE_SUBMITTED;
  private readonly artifacts = new Map<string, Artifact>();
  private statusMessage: Message | undefined;
  private directMessage: Message | undefined;

  public get phase(): TurnPhase {
    if (this.directMessage) {
      return 'completed';
    }
    return PHASES[this.state] ?? 'active';
  }

  public get isSettled(): boolean {
    return this.phase !== 'active';
  }

  public get prompt(): Message | undefined {
    return this.statusMessage;
  }

  public apply(result: Message | Task | StreamResponse): void {
    if (isTask(result)) {
      this.applyTask(result);
    } else if (isMessage(result)) {
      this.applyMessage(result);
    } else {
      this.applyStream(result);
    }
  }

  /** The artifacts produced so far or, without artifacts, the agent's last message. */
  public answerParts(): Part[] {
    const artifactParts = [...this.artifacts.values()].flatMap((artifact) => artifact.parts);
    if (artifactParts.length) {
      return artifactParts;
    }
    return (this.directMessage ?? this.statusMessage)?.parts ?? [];
  }

  public statusText(): string {
    return textOf(this.statusMessage?.parts ?? []);
  }

  private applyStream(response: StreamResponse): void {
    const payload = response.payload;
    if (!payload) {
      return;
    }
    if (payload.$case === 'task') {
      this.applyTask(payload.value);
    } else if (payload.$case === 'message') {
      this.applyMessage(payload.value);
    } else if (payload.$case === 'statusUpdate') {
      this.bind(payload.value.taskId, payload.value.contextId);
      this.applyStatus(payload.value.status);
    } else if (payload.$case === 'artifactUpdate' && payload.value.artifact) {
      this.bind(payload.value.taskId, payload.value.contextId);
      this.applyArtifact(payload.value.artifact, payload.value.append);
    }
  }

  private applyTask(task: Task): void {
    this.bind(task.id, task.contextId);
    this.applyStatus(task.status);
    for (const artifact of task.artifacts) {
      this.applyArtifact(artifact, false);
    }
  }

  private applyMessage(message: Message): void {
    this.bind(message.taskId || undefined, message.contextId || undefined);
    if (message.taskId) {
      this.statusMessage = message;
    } else {
      this.directMessage = message;
    }
  }

  private applyStatus(status: TaskStatus | undefined): void {
    if (!status) {
      return;
    }
    this.state = status.state;
    if (status.message) {
      this.statusMessage = status.message;
    }
  }

  private applyArtifact(artifact: Artifact, append: boolean): void {
    const existing = this.artifacts.get(artifact.artifactId);
    this.artifacts.set(
      artifact.artifactId,
      append && existing
        ? { ...existing, parts: [...existing.parts, ...artifact.parts] }
        : artifact,
    );
  }

  private bind(taskId: string | undefined, contextId: string | undefined): void {
    this.taskId ||= taskId;
    this.contextId ||= contextId;
  }
}

export function textOf(parts: Part[]): string {
  return parts
    .map((part) => (part.content?.$case === 'text' ? part.content.value : ''))
    .filter(Boolean)
    .join('');
}

/** Renders remote parts as chat markdown; structured data becomes a fenced JSON block. */
export function renderParts(parts: Part[], renderFile: (part: Part) => string): string {
  const blocks: string[] = [];
  let text = '';
  for (const part of parts) {
    const content = part.content;
    if (content?.$case === 'text') {
      text += content.value;
      continue;
    }
    if (text) {
      blocks.push(text);
      text = '';
    }
    if (content?.$case === 'data') {
      blocks.push(`\`\`\`json\n${JSON.stringify(content.value, null, 2)}\n\`\`\``);
    } else if (content?.$case === 'raw' || content?.$case === 'url') {
      blocks.push(renderFile(part));
    }
  }
  if (text) {
    blocks.push(text);
  }
  return blocks.join('\n\n');
}
