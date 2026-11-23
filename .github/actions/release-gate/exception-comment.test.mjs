import assert from 'node:assert/strict';
import test from 'node:test';
import { buildComment, MARKER } from './exception-comment.mjs';

const input = (overrides = {}) => ({
  existingBody: undefined,
  action: 'labeled',
  actor: 'alice',
  time: '2026-10-27T10:00:00.000Z',
  sha: 'abc1234def5678',
  ...overrides,
});

test('starts the comment with the marker', () => {
  assert.equal(buildComment(input()).split('\n')[0], MARKER);
});

test('records who set the label, when, and at which commit', () => {
  const body = buildComment(input());
  assert.match(body, /State: \*\*ACTIVE\*\*/);
  assert.match(body, /Set by alice at 2026-10-27T10:00:00\.000Z\./);
  assert.match(
    body,
    /- 2026-10-27T10:00:00\.000Z: alice added the label security-exception at commit abc1234/,
  );
});

test('records who removed the label and keeps the earlier history', () => {
  const first = buildComment(input());
  const second = buildComment(
    input({
      existingBody: first,
      action: 'unlabeled',
      actor: 'bob',
      time: '2026-10-27T11:00:00.000Z',
    }),
  );
  assert.match(second, /State: \*\*REMOVED\*\*/);
  assert.match(second, /Removed by bob at 2026-10-27T11:00:00\.000Z\./);
  assert.match(second, /alice added the label/);
  assert.match(second, /bob removed the label/);
  assert.equal(second.split('\n').filter((line) => line.startsWith('- ')).length, 2);
});

test('keeps only the 20 newest history entries', () => {
  let body;
  for (let index = 0; index < 25; index++) {
    body = buildComment(input({ existingBody: body, actor: `user${index}` }));
  }
  const entries = body.split('\n').filter((line) => line.startsWith('- '));
  assert.equal(entries.length, 20);
  assert.match(entries[0], /user5 /);
  assert.match(entries.at(-1), /user24 /);
});
