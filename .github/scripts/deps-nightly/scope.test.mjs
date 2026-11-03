import assert from 'node:assert';
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
deps = package.json, pnpm-lock.yaml
`;

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

  it('returns main when a lock file comes with a file of another scope', () => {
    assert.strictEqual(
      commitScope(['pnpm-lock.yaml', 'pnpm-workspace.yaml'], gitcommitizen),
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
