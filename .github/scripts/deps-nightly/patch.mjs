import assert from 'node:assert';
import { normalizeName, pinEdit } from './locks.mjs';
import { ACTION_FILES, DOCKERFILES, TERRAFORM_FILES, TERRAFORM_LOCKS } from './repo.mjs';
import { runOrThrow } from './run.mjs';

const ALLOWED_FILES = {
  npm: /(^|\/)(package\.json|pnpm-lock\.yaml|pnpm-workspace\.yaml)$/,
  uv: /(^|\/)(pyproject\.toml|uv\.lock)$/,
  actions: ACTION_FILES,
  docker: DOCKERFILES,
  terraform: new RegExp(`${TERRAFORM_FILES.source}|${TERRAFORM_LOCKS.source}`),
};
const NEW_FILES = { terraform: TERRAFORM_LOCKS };

export function assertAllowedChanges({ ecosystem, status, summary }) {
  const allowed = ALLOWED_FILES[ecosystem];
  assert.ok(allowed, `Unknown ecosystem ${ecosystem}`);
  assert.strictEqual(summary.trim(), '', `The patch adds, removes or renames files:\n${summary}`);
  for (const line of status.split('\n').filter(Boolean)) {
    const path = line.slice(3);
    const created = line.startsWith('?? ') && NEW_FILES[ecosystem]?.test(path);
    assert.ok(
      line.startsWith(' M ') || created,
      `The patch makes a change that is not an edit: ${line}`,
    );
    assert.ok(allowed.test(path), `A ${ecosystem} update does not change ${path}`);
  }
}

export function assertRequirementEdits({ members, before, after }) {
  for (const [path, text] of Object.entries(before)) {
    const expected = members.reduce(
      (current, { name, to }) => pinEdit(current, normalizeName(name), to),
      text,
    );
    assert.strictEqual(after[path], expected, `${path} has an edit that is no requirement bump`);
  }
}

export function readChanges() {
  return {
    status: runOrThrow('git', ['status', '--porcelain', '--untracked-files=all']),
    summary: runOrThrow('git', ['diff', '--summary']),
  };
}
