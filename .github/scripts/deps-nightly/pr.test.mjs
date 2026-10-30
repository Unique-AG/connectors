import assert from 'node:assert';
import { describe, it } from 'node:test';
import { renderPr } from './pr.mjs';

const gitcommitizen = `[scopes]
deps = pnpm-lock.yaml, package.json
ci = .github/**
logger = packages/logger/**
`;
const pnpmLock = (zod) => `lockfileVersion: '9.0'

importers:

  .:
    dependencies:
      zod:
        version: ${zod}

packages:

  zod@${zod}:
    resolution: {integrity: sha512-ccc}
`;
const uvLock = (httpx2) => `version = 1

[[package]]
name = "httpx2"
version = "${httpx2}"
source = { registry = "https://pypi.org/simple" }
`;
const npmEntry = {
  ecosystem: 'npm',
  key: 'npm:zod',
  name: 'zod',
  isGroup: false,
  members: [{ name: 'zod', from: '4.6.5', to: '4.6.7', direct: true }],
};
const uvEntry = {
  ecosystem: 'uv',
  key: 'uv:httpx2',
  name: 'httpx2',
  isGroup: false,
  members: [{ name: 'httpx2', from: '1.0.0', to: '1.1.0', direct: true }],
};
const actionsEntry = {
  ecosystem: 'actions',
  key: 'actions:actions/checkout',
  name: 'actions/checkout',
  isGroup: false,
  members: [{ name: 'actions/checkout', from: 'v7.0.0', to: 'v7.0.1' }],
};

describe('renderPr', () => {
  it('derives the npm package list and importers from the lock files', () => {
    const { title, body } = renderPr({
      entry: npmEntry,
      files: ['package.json', 'pnpm-lock.yaml'],
      before: { 'pnpm-lock.yaml': pnpmLock('4.6.5') },
      after: { 'pnpm-lock.yaml': pnpmLock('4.6.7') },
      gitcommitizen,
      cooldownDays: 3,
    });
    assert.strictEqual(title, 'build(deps): bump zod from 4.6.5 to 4.6.7');
    assert.match(body, /`zod`: 4\.6\.5 -> 4\.6\.7/);
    assert.match(body, /- `\.`/);
  });

  it('derives the uv package list and folders from the lock files', () => {
    const { body } = renderPr({
      entry: uvEntry,
      files: ['services/hello/uv.lock'],
      before: {
        'services/hello/uv.lock': uvLock('1.0.0'),
        'services/other/uv.lock': uvLock('1.0.0'),
      },
      after: {
        'services/hello/uv.lock': uvLock('1.1.0'),
        'services/other/uv.lock': uvLock('1.0.0'),
      },
      gitcommitizen,
      cooldownDays: 3,
    });
    assert.match(body, /`httpx2`: 1\.0\.0 -> 1\.1\.0/);
    assert.match(body, /- `services\/hello`/);
    assert.doesNotMatch(body, /services\/other/);
  });

  it('takes the versions from the plan entry and the files from the patch for actions', () => {
    const { title, body } = renderPr({
      entry: actionsEntry,
      files: ['.github/workflows/ci.yaml'],
      before: {},
      after: {},
      gitcommitizen,
      cooldownDays: 3,
    });
    assert.strictEqual(title, 'build(ci): bump actions/checkout from v7.0.0 to v7.0.1');
    assert.match(body, /`actions\/checkout`: v7\.0\.0 -> v7\.0\.1/);
    assert.match(body, /- `\.github\/workflows\/ci\.yaml`/);
  });

  it('changes the title scope when the changed files change', () => {
    const render = (files) =>
      renderPr({
        entry: actionsEntry,
        files,
        before: {},
        after: {},
        gitcommitizen,
        cooldownDays: 3,
      }).title;
    assert.strictEqual(
      render(['packages/logger/Dockerfile']),
      'build(logger): bump actions/checkout from v7.0.0 to v7.0.1',
    );
    assert.strictEqual(
      render(['packages/logger/Dockerfile', '.github/a.yaml']),
      'build(main): bump actions/checkout from v7.0.0 to v7.0.1',
    );
  });
});
