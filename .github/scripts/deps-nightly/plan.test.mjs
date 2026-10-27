import assert from 'node:assert';
import { describe, it } from 'node:test';
import {
  buildPlan,
  latestEligibleVersions,
  npmCandidates,
  renderSummary,
  uvCandidates,
} from './plan.mjs';

const NOW = Date.parse('2026-10-27T00:00:00Z');
const file = (uploaded, yanked = false) => ({ upload_time_iso_8601: uploaded, yanked });

describe('npmCandidates', () => {
  const outdated = {
    zod: { wanted: '4.6.5', latest: '4.6.7' },
    same: { wanted: '1.0.0', latest: '1.0.0' },
    older: { wanted: '2.0.0', latest: '1.9.0' },
    esbuild: { wanted: '0.28.2', latest: '0.29.0' },
  };
  const lockChanges = [
    { name: 'undici', from: ['8.10.2'], to: ['8.12.3'] },
    { name: 'zod', from: ['4.6.5'], to: ['4.6.7'] },
    { name: 'typed-emitter', from: [], to: ['2.1.0'] },
    { name: 'uuid', from: ['9.0.0'], to: ['9.0.1'] },
  ];
  const result = npmCandidates({
    outdated,
    lockChanges,
    overrides: { esbuild: '0.28.2', 'uuid@<11.1.1': '11.1.1' },
  });

  it('lists direct and indirect updates', () => {
    assert.deepStrictEqual(
      result.candidates.map(({ name, from, to, direct }) => [name, from, to, direct]),
      [
        ['zod', '4.6.5', '4.6.7', true],
        ['undici', '8.10.2', '8.12.3', false],
      ],
    );
  });

  it('leaves a package that an override pins for a person', () => {
    assert.deepStrictEqual(
      result.needsPerson.map(({ name }) => name),
      ['older', 'esbuild', 'uuid'],
    );
  });

  it('explains a target that is older than the current version', () => {
    assert.match(result.needsPerson[0].reason, /1\.9\.0 is older than 2\.0\.0/);
  });
});

describe('latestEligibleVersions', () => {
  const pypi = {
    releases: {
      '1.0.0': [file('2026-09-01T00:00:00Z')],
      '1.1.0': [file('2026-10-01T00:00:00Z')],
      '1.2.0': [file('2026-10-25T00:00:00Z')],
      '1.3.0': [file('2026-10-01T00:00:00Z', true)],
      '2.0.0rc1': [file('2026-10-01T00:00:00Z')],
      '1.4.0': [],
    },
  };
  const latestAt = async (now) => [
    ...(await latestEligibleVersions(['a'], async () => pypi, now, 3)),
  ];

  it('picks the newest stable release that is old enough and not yanked', async () => {
    assert.deepStrictEqual(await latestAt(NOW), [['a', '1.1.0']]);
  });

  it('leaves out a name when no release is old enough', async () => {
    assert.deepStrictEqual(await latestAt(Date.parse('2026-08-01T00:00:00Z')), []);
  });

  it('asks for each name and keeps the names that have a version', async () => {
    const asked = [];
    const fetchPypi = async (name) => {
      asked.push(name);
      return name === 'a' ? { releases: { '1.0.0': [file('2026-09-01T00:00:00Z')] } } : undefined;
    };
    const latest = await latestEligibleVersions(['a', 'b'], fetchPypi, NOW, 3);
    assert.deepStrictEqual([...latest], [['a', '1.0.0']]);
    assert.deepStrictEqual(asked, ['a', 'b']);
  });
});

describe('uvCandidates', () => {
  const lock = (name, version) => `[[package]]
name = "${name}"
version = "${version}"
source = { registry = "https://pypi.org/simple" }
`;
  const project = (folder, pins, locks, updates = []) => ({
    project: folder,
    pyproject: `dependencies = [\n${pins.map((pin) => `    "${pin}",`).join('\n')}\n]\n`,
    lock: locks.map(([name, version]) => lock(name, version)).join('\n'),
    updates,
  });

  it('uses the lowest target of the projects that hold a package', () => {
    const { candidates } = uvCandidates({
      projects: [
        project(
          'a',
          [],
          [['tomlkit', '0.15.1']],
          [{ name: 'tomlkit', from: '0.15.1', to: '0.15.3' }],
        ),
        project(
          'b',
          [],
          [['tomlkit', '0.15.1']],
          [{ name: 'tomlkit', from: '0.15.1', to: '0.15.2' }],
        ),
      ],
      latest: new Map(),
    });
    assert.deepStrictEqual(candidates, [
      { ecosystem: 'uv', name: 'tomlkit', from: '0.15.1', to: '0.15.2', direct: false },
    ]);
  });

  it('proposes the newest release for an exact pin', () => {
    const { candidates } = uvCandidates({
      projects: [project('a', ['ruff==0.17.0'], [['ruff', '0.17.0']])],
      latest: new Map([['ruff', '0.17.2']]),
    });
    assert.deepStrictEqual(candidates, [
      { ecosystem: 'uv', name: 'ruff', from: '0.17.0', to: '0.17.2', direct: true },
    ]);
  });

  it('leaves a pin for a person when a limit in another project forbids the release', () => {
    const { candidates, needsPerson } = uvCandidates({
      projects: [
        project('services/a', ['fastmcp==4.1.3'], [['fastmcp', '4.1.3']]),
        project('packages/b', ['fastmcp>=4.1,<5'], [['fastmcp', '4.1.3']]),
      ],
      latest: new Map([['fastmcp', '5.0.0']]),
    });
    assert.deepStrictEqual(candidates, []);
    assert.deepStrictEqual(needsPerson, [
      {
        ecosystem: 'uv',
        name: 'fastmcp',
        reason: 'Version 5.0.0 breaks the limit >=4.1,<5 in packages/b.',
      },
    ]);
  });

  it('leaves a package for a person when the target is older than a locked version', () => {
    const { candidates, needsPerson } = uvCandidates({
      projects: [
        project(
          'a',
          [],
          [['tomlkit', '0.15.1']],
          [{ name: 'tomlkit', from: '0.15.1', to: '0.15.2' }],
        ),
        project('b', [], [['tomlkit', '0.16.0']]),
      ],
      latest: new Map(),
    });
    assert.deepStrictEqual(candidates, []);
    assert.match(needsPerson[0].reason, /0\.15\.2 is older than 0\.16\.0 in b/);
  });

  it('skips a package that is already at the target everywhere', () => {
    const { candidates } = uvCandidates({
      projects: [project('a', ['ruff==0.17.2'], [['ruff', '0.17.2']])],
      latest: new Map([['ruff', '0.17.2']]),
    });
    assert.deepStrictEqual(candidates, []);
  });
});

describe('buildPlan', () => {
  const config = {
    maxNewPullRequests: 3,
    groups: [
      { name: 'opentelemetry', ecosystem: 'uv', patterns: ['opentelemetry-*'] },
      { name: 'fastmcp', ecosystem: 'uv', patterns: ['fastmcp', 'fastmcp-slim'] },
    ],
  };
  const candidate = (ecosystem, name, direct = false) => ({
    ecosystem,
    name,
    from: '1.0.0',
    to: '1.1.0',
    direct,
  });

  it('joins the members of a group into one entry', () => {
    const { entries } = buildPlan({
      candidates: [
        candidate('uv', 'opentelemetry-api'),
        candidate('uv', 'opentelemetry-sdk'),
        candidate('uv', 'x'),
      ],
      needsPerson: [],
      config,
      openBranches: [],
    });
    assert.deepStrictEqual(
      entries.map(({ slug, isGroup, members }) => [slug, isGroup, members.length]),
      [
        ['uv-opentelemetry', true, 2],
        ['uv-x', false, 1],
      ],
    );
  });

  it('builds a branch safe slug from a scoped name', () => {
    const { entries } = buildPlan({
      candidates: [candidate('npm', '@types/node'), candidate('uv', 'Typing_Extensions')],
      needsPerson: [],
      config,
      openBranches: [],
    });
    assert.deepStrictEqual(entries.map(({ slug }) => slug).sort(), [
      'npm-types-node',
      'uv-typing-extensions',
    ]);
  });

  it('treats a group with one member as a plain package', () => {
    const { entries } = buildPlan({
      candidates: [candidate('uv', 'fastmcp')],
      needsPerson: [],
      config,
      openBranches: [],
    });
    assert.deepStrictEqual([entries[0].slug, entries[0].isGroup], ['uv-fastmcp', false]);
  });

  it('skips a name that has an open pull request', () => {
    const { entries, skipped } = buildPlan({
      candidates: [candidate('npm', 'zod'), candidate('npm', 'pino')],
      needsPerson: [],
      config,
      openBranches: ['deps/npm-zod', 'feature/other'],
    });
    assert.deepStrictEqual(
      entries.map(({ slug }) => slug),
      ['npm-pino'],
    );
    assert.deepStrictEqual(
      skipped.map(({ slug }) => slug),
      ['npm-zod'],
    );
  });

  it('caps new pull requests, mixes ecosystems and puts direct updates first', () => {
    const { entries, deferred } = buildPlan({
      candidates: [
        candidate('npm', 'a'),
        candidate('npm', 'b', true),
        candidate('npm', 'c', true),
        candidate('uv', 'd'),
        candidate('uv', 'e', true),
      ],
      needsPerson: [],
      config,
      openBranches: [],
    });
    assert.deepStrictEqual(
      entries.map(({ slug }) => slug),
      ['npm-b', 'uv-e', 'npm-c'],
    );
    assert.deepStrictEqual(
      deferred.map(({ slug }) => slug),
      ['uv-d', 'npm-a'],
    );
  });
});

describe('renderSummary', () => {
  it('lists each section and ends the needs a person list with the reason', () => {
    const summary = renderSummary(
      {
        entries: [
          { ecosystem: 'npm', name: 'zod', isGroup: false, members: [{ from: '1', to: '2' }] },
        ],
        skipped: [],
        deferred: [],
        needsPerson: [{ ecosystem: 'uv', name: 'fastmcp', reason: 'A limit forbids it.' }],
      },
      'Plan only.',
    );
    assert.match(summary, /Plan only\./);
    assert.match(summary, /### Pull requests for this run \(1\)\n\n- npm zod: 1 -> 2/);
    assert.match(summary, /### Needs a person \(1\)\n\n- uv fastmcp: A limit forbids it\./);
    assert.doesNotMatch(summary, /Skipped/);
  });
});
