import assert from 'node:assert';
import { readFileSync } from 'node:fs';
import { describe, it } from 'node:test';
import { commitScope } from './scope.mjs';

const repositoryGitcommitizen = readFileSync(
  new URL('../../../.gitcommitizen', import.meta.url),
  'utf8',
);

const fixture = `[settings]
multi-scope = true

[scopes]
hello-mcp = services/hello-mcp/**
services = services/**
ci = .github/**
main = *, .*
deps = **/uv.lock, .github/workflows/**
`;

describe('commitScope', () => {
  it('prefers deps over a scope that is listed before it', () => {
    assert.strictEqual(commitScope(['services/hello-mcp/uv.lock'], fixture), 'deps');
    assert.strictEqual(commitScope(['.github/workflows/ci.yaml'], fixture), 'deps');
  });

  it('returns the first listed scope that every file matches', () => {
    const files = ['services/hello-mcp/a.py', 'services/hello-mcp/b.py'];
    assert.strictEqual(commitScope(files, fixture), 'hello-mcp');
  });

  it('returns main when no scope matches every file', () => {
    assert.strictEqual(commitScope(['services/hello-mcp/a.py', '.github/a.mjs'], fixture), 'main');
  });

  it('lets a star match inside one directory only', () => {
    const markdown = '[scopes]\ndocs = *.md\nmain = *, .*\n';
    assert.strictEqual(commitScope(['README.md'], markdown), 'docs');
    assert.strictEqual(commitScope(['services/a/README.md'], markdown), 'main');
  });

  it('returns main for an empty list', () => {
    assert.strictEqual(commitScope([], fixture), 'main');
  });

  for (const [name, files, scope] of [
    ['a catalog change with the lock file', ['pnpm-lock.yaml', 'pnpm-workspace.yaml'], 'deps'],
    [
      'package.json files in several projects',
      ['services/kb-mcp/package.json', 'packages/utils/package.json', 'pnpm-lock.yaml'],
      'deps',
    ],
    ['the lock file of one service', ['services/hello-mcp/uv.lock'], 'deps'],
    [
      'Dockerfiles in several services',
      ['services/hello-mcp/deploy/Dockerfile', 'services/kb-mcp/deploy/Dockerfile'],
      'deps',
    ],
    [
      'Terraform files in one module',
      [
        'services/hello-mcp/deploy/terraform/versions.tf',
        'services/hello-mcp/deploy/terraform/.terraform.lock.hcl',
      ],
      'deps',
    ],
    ['a pinned action in a workflow', ['.github/workflows/ci.yaml'], 'deps'],
    [
      'a bump with a code fix in one service',
      ['services/hello-mcp/uv.lock', 'services/hello-mcp/src/a.py'],
      'hello-mcp',
    ],
    [
      'code in several services',
      ['services/hello-mcp/src/a.py', 'services/kb-mcp/src/b.py'],
      'services',
    ],
    [
      'code in several packages',
      ['packages/utils/src/a.ts', 'packages/mcp-oauth/src/b.ts'],
      'packages',
    ],
    ['code in a package and the lock file', ['packages/proxy/src/a.ts', 'pnpm-lock.yaml'], 'main'],
    [
      'code in a service and a package',
      ['services/hello-mcp/src/a.py', 'packages/utils/src/a.ts'],
      'main',
    ],
    ['the docs', ['docs/security/a.md', 'SECURITY-PROCESS.md'], 'docs'],
    ['an agent skill', ['agentic/skills/a/SKILL.md'], 'agentic'],
    ['a script of the workflows', ['.github/scripts/a.mjs'], 'ci'],
    ['the readme of a service', ['services/hello-mcp/README.md'], 'hello-mcp'],
  ]) {
    it(`gives the scope ${scope} for ${name} in the .gitcommitizen of the repository`, () => {
      assert.strictEqual(commitScope(files, repositoryGitcommitizen), scope);
    });
  }
});
