import { type Message, type Part, Role, type Task, TaskState } from '@a2a-js/sdk';
import { describe, expect, it } from 'vitest';
import { RemoteTurn, renderParts } from './remote-turn.js';

function text(value: string): Part {
  return { content: { $case: 'text', value }, metadata: undefined, filename: '', mediaType: '' };
}

function message(parts: Part[], taskId = ''): Message {
  return {
    messageId: 'm-1',
    contextId: 'ctx-1',
    taskId,
    role: Role.ROLE_AGENT,
    parts,
    metadata: undefined,
    extensions: [],
    referenceTaskIds: [],
  };
}

function task(state: TaskState, parts: Part[] = []): Task {
  return {
    id: 'task-1',
    contextId: 'ctx-1',
    status: { state, message: undefined, timestamp: undefined },
    artifacts: parts.length
      ? [
          {
            artifactId: 'a-1',
            name: '',
            description: '',
            parts,
            metadata: undefined,
            extensions: [],
          },
        ]
      : [],
    history: [],
    metadata: undefined,
  };
}

const renderFile = (part: Part): string => `[file ${part.filename}]`;

describe('RemoteTurn', () => {
  it('treats a direct Message reply as a completed turn without a task', () => {
    const turn = new RemoteTurn();
    turn.apply(message([text('Hi')]));
    expect(turn.phase).toBe('completed');
    expect(turn.taskId).toBeUndefined();
    expect(renderParts(turn.answerParts(), renderFile)).toBe('Hi');
  });

  it('follows task snapshots from working to completed and keeps artifacts', () => {
    const turn = new RemoteTurn();
    turn.apply(task(TaskState.TASK_STATE_WORKING));
    expect(turn.phase).toBe('active');
    expect(turn.taskId).toBe('task-1');
    turn.apply(task(TaskState.TASK_STATE_COMPLETED, [text('Done')]));
    expect(turn.phase).toBe('completed');
    expect(renderParts(turn.answerParts(), renderFile)).toBe('Done');
  });

  it('appends streamed artifact chunks in order', () => {
    const turn = new RemoteTurn();
    turn.apply({ payload: { $case: 'task', value: task(TaskState.TASK_STATE_WORKING) } });
    for (const [index, chunk] of ['Echo:', ' a', ' b'].entries()) {
      turn.apply({
        payload: {
          $case: 'artifactUpdate',
          value: {
            taskId: 'task-1',
            contextId: 'ctx-1',
            artifact: {
              artifactId: 'answer',
              name: '',
              description: '',
              parts: [text(chunk)],
              metadata: undefined,
              extensions: [],
            },
            append: index > 0,
            lastChunk: index === 2,
            metadata: undefined,
          },
        },
      });
    }
    expect(renderParts(turn.answerParts(), renderFile)).toBe('Echo: a b');
  });

  it.each([
    [TaskState.TASK_STATE_FAILED, 'failed'],
    [TaskState.TASK_STATE_REJECTED, 'rejected'],
    [TaskState.TASK_STATE_CANCELED, 'canceled'],
    [TaskState.TASK_STATE_INPUT_REQUIRED, 'input-required'],
    [TaskState.TASK_STATE_AUTH_REQUIRED, 'auth-required'],
  ])('maps task state %s to phase %s', (state, phase) => {
    const turn = new RemoteTurn();
    turn.apply(task(state));
    expect(turn.phase).toBe(phase);
    expect(turn.isSettled).toBe(true);
  });

  it('renders structured data as fenced JSON and files through the file renderer', () => {
    const parts: Part[] = [
      text('Result:'),
      {
        content: { $case: 'data', value: { a: 1 } },
        metadata: undefined,
        filename: '',
        mediaType: '',
      },
      {
        content: { $case: 'url', value: 'https://remote.example/f' },
        metadata: undefined,
        filename: 'f.csv',
        mediaType: 'text/csv',
      },
    ];
    expect(renderParts(parts, renderFile)).toBe(
      'Result:\n\n```json\n{\n  "a": 1\n}\n```\n\n[file f.csv]',
    );
  });
});
