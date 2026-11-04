import assert from 'node:assert';
import { readFileSync } from 'node:fs';
import { describe, it } from 'node:test';
import { commitScope } from './scope.mjs';

const gitcommitizen = `[settings]
multi-scope = true

[scopes]
hello-mcp = services/hello-mcp/**
kb-mcp = services/kb-mcp/**
mcp-configs = packages/mcp-configs/**
ci = .github/**, pnpm-workspace.yaml
main = *, .*
deps = package.json, pnpm-lock.yaml, pnpm-workspace.yaml
`;

const repositoryGitcommitizen = readFileSync(
  new URL('../../../.gitcommitizen', import.meta.url),
  'utf8',
);

describe('commitScope', () => {
  it('returns deps when every file belongs to deps', () => {
    assert.strictEqual(commitScope(['pnpm-lock.yaml', 'package.json'], gitcommitizen), 'deps');
  });

  it('returns the scope of a single project', () => {
    const files = ['services/hello-mcp/uv.lock', 'services/hello-mcp/pyproject.toml'];
    assert.strictEqual(commitScope(files, gitcommitizen), 'hello-mcp');
  });

  it('returns main when files belong to two scopes', () => {
    const files = ['services/hello-mcp/uv.lock', 'services/kb-mcp/uv.lock'];
    assert.strictEqual(commitScope(files, gitcommitizen), 'main');
  });

  it('returns deps when a catalog change comes with the lock file', () => {
    assert.strictEqual(
      commitScope(['pnpm-lock.yaml', 'pnpm-workspace.yaml'], gitcommitizen),
      'deps',
    );
  });

  it('returns deps for a catalog change in the .gitcommitizen of the repository', () => {
    assert.strictEqual(
      commitScope(['pnpm-lock.yaml', 'pnpm-workspace.yaml'], repositoryGitcommitizen),
      'deps',
    );
  });

  it('returns main when a lock file comes with a file of another scope', () => {
    assert.strictEqual(
      commitScope(['pnpm-lock.yaml', '.github/workflows/ci.yaml'], gitcommitizen),
      'main',
    );
  });

  it('returns main for a file that no scope owns', () => {
    assert.strictEqual(commitScope(['docs/readme.md'], gitcommitizen), 'main');
  });

  it('returns main for an empty list', () => {
    assert.strictEqual(commitScope([], gitcommitizen), 'main');
  });
});
