import assert from 'node:assert';
import { describe, it } from 'node:test';
import {
  buildPlan,
  latestEligibleVersions,
  npmCandidates,
  renderSummary,
  uvCandidates,
} from './plan.mjs';
import { markerOf } from './state.mjs';

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

  it('marks a major bump, direct or indirect', () => {
    const { candidates } = npmCandidates({
      outdated: { zod: { wanted: '4.6.5', latest: '5.0.0' } },
      lockChanges: [{ name: 'undici', from: ['7.9.0'], to: ['8.0.0'] }],
      overrides: {},
    });
    assert.deepStrictEqual(
      candidates.map(({ name, data }) => [name, data]),
      [
        ['zod', { major: true }],
        ['undici', { major: true }],
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
    ...(await latestEligibleVersions(['a'], async () => pypi, now, 3)).latest,
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
    const { latest } = await latestEligibleVersions(['a', 'b'], fetchPypi, NOW, 3);
    assert.deepStrictEqual([...latest], [['a', '1.0.0']]);
    assert.deepStrictEqual(asked, ['a', 'b']);
  });

  it('puts a name that PyPI did not answer into needsPerson', async () => {
    const fetchPypi = async (name) => {
      if (name === 'down') {
        throw new Error('network');
      }
      return name === 'missing' ? undefined : pypi;
    };
    const { latest, needsPerson } = await latestEligibleVersions(
      ['a', 'missing', 'down'],
      fetchPypi,
      NOW,
      3,
    );
    assert.deepStrictEqual([...latest], [['a', '1.1.0']]);
    assert.deepStrictEqual(needsPerson, [
      { ecosystem: 'uv', name: 'missing', reason: 'PyPI did not answer for missing.' },
      { ecosystem: 'uv', name: 'down', reason: 'PyPI did not answer for down.' },
    ]);
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

  it('marks a major bump and matches a lock that spells the name with an underscore', () => {
    const { candidates } = uvCandidates({
      projects: [
        project(
          'a',
          [],
          [['typing_extensions', '4.15.0']],
          [{ name: 'typing_extensions', from: '4.15.0', to: '5.0.0' }],
        ),
      ],
      latest: new Map(),
    });
    assert.deepStrictEqual(candidates, [
      {
        ecosystem: 'uv',
        name: 'typing-extensions',
        from: '4.15.0',
        to: '5.0.0',
        direct: false,
        data: { major: true },
      },
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
    });
    assert.deepStrictEqual(entries.map(({ slug }) => slug).sort(), [
      'npm-types-node',
      'uv-typing-extensions',
    ]);
  });

  it('names a group with one member as a plain package and keeps the group branch', () => {
    const { entries } = buildPlan({
      candidates: [candidate('uv', 'fastmcp')],
      needsPerson: [],
      config,
    });
    assert.deepStrictEqual(
      [entries[0].slug, entries[0].name, entries[0].isGroup],
      ['uv-fastmcp', 'fastmcp', false],
    );
    const single = buildPlan({
      candidates: [candidate('uv', 'opentelemetry-api')],
      needsPerson: [],
      config,
    }).entries[0];
    assert.deepStrictEqual([single.slug, single.name], ['uv-opentelemetry', 'opentelemetry-api']);
  });

  it('puts the major bumps of a group in a pull request of their own', () => {
    const major = { ...candidate('uv', 'opentelemetry-sdk'), data: { major: true } };
    const { entries } = buildPlan({
      candidates: [candidate('uv', 'opentelemetry-api'), major],
      needsPerson: [],
      config,
    });
    assert.deepStrictEqual(entries.map(({ slug }) => slug).sort(), [
      'uv-opentelemetry',
      'uv-opentelemetry-major',
    ]);
  });

  it('gives colliding slugs a stable suffix and keeps the unique ones', () => {
    const plan = () =>
      buildPlan({
        candidates: [
          candidate('npm', '@babel/core'),
          candidate('npm', 'babel-core'),
          candidate('npm', 'zod'),
        ],
        needsPerson: [],
        config,
      });
    const slugs = () => Object.fromEntries(plan().entries.map(({ name, slug }) => [name, slug]));
    const bySlug = slugs();
    assert.strictEqual(bySlug.zod, 'npm-zod');
    assert.match(bySlug['@babel/core'], /^npm-babel-core-[0-9a-f]{6}$/);
    assert.match(bySlug['babel-core'], /^npm-babel-core-[0-9a-f]{6}$/);
    assert.notStrictEqual(bySlug['@babel/core'], bySlug['babel-core']);
    assert.deepStrictEqual(slugs(), bySlug);
  });

  describe('with a matrix over the limit', () => {
    const many = (count) =>
      Array.from({ length: count }, (_, index) => candidate('npm', `pkg-${index}`));
    const pull = (index, labels = []) => ({
      number: index,
      branch: `deps/npm-pkg-${index}`,
      body: '',
      labels,
      behindBy: 1,
      humanCommits: false,
    });

    it('keeps at most 250 entries and returns the rest as deferred', () => {
      const { entries, updates, deferred } = buildPlan({
        candidates: many(260),
        needsPerson: [],
        config,
      });
      assert.strictEqual(entries.length, 250);
      assert.strictEqual(updates.length, 0);
      assert.strictEqual(deferred.length, 10);
    });

    it('puts the existing pull requests first and defers the new ones', () => {
      const { entries, deferred } = buildPlan({
        candidates: many(260),
        needsPerson: [],
        config,
        openPulls: Array.from({ length: 5 }, (_, index) => pull(255 + index)),
      });
      assert.deepStrictEqual(
        entries.slice(0, 5).map(({ action }) => action),
        Array(5).fill('replace'),
      );
      assert.ok(deferred.every(({ action }) => action === 'new'));
    });

    it('caps the updates too', () => {
      const candidates = many(255);
      const first = buildPlan({ candidates, needsPerson: [], config });
      const openPulls = [...first.entries, ...first.deferred].map(({ key, name }, index) => ({
        ...pull(index, ['ai-assisted']),
        branch: `deps/npm-${name}`,
        body: markerOf(key),
      }));
      const { updates, deferred } = buildPlan({ candidates, needsPerson: [], config, openPulls });
      assert.strictEqual(updates.length, 250);
      assert.strictEqual(deferred.length, 5);
    });
  });

  describe('with open pull requests', () => {
    const [zod] = buildPlan({
      candidates: [candidate('npm', 'zod')],
      needsPerson: [],
      config,
    }).entries;
    const pull = (overrides) => ({
      number: 7,
      branch: 'deps/npm-zod',
      body: markerOf(zod.key),
      behindBy: 2,
      humanCommits: false,
      labels: [],
      ...overrides,
    });
    const plan = (openPulls, extra = {}) =>
      buildPlan({
        candidates: [candidate('npm', 'zod'), candidate('npm', 'pino')],
        needsPerson: [],
        config,
        openPulls,
        ...extra,
      });

    it('skips a pull request that is up to date with main', () => {
      const { entries, skipped } = plan([pull({ behindBy: 0 })]);
      assert.deepStrictEqual(
        entries.map(({ slug }) => slug),
        ['npm-pino'],
      );
      assert.deepStrictEqual(
        skipped.map(({ slug, reason }) => [slug, reason]),
        [['npm-zod', '#7 is up to date']],
      );
    });

    it('rebuilds an unhandled pull request that is behind main', () => {
      const { entries } = plan([pull()]);
      assert.deepStrictEqual(
        entries.map(({ slug, action, number }) => [slug, action, number]),
        [
          ['npm-zod', 'rebuild', 7],
          ['npm-pino', 'new', undefined],
        ],
      );
    });

    it('only merges main into a pull request that has a commit from a person', () => {
      const { entries, updates } = plan([pull({ humanCommits: true })]);
      assert.deepStrictEqual(
        updates.map(({ slug, number }) => [slug, number]),
        [['npm-zod', 7]],
      );
      assert.deepStrictEqual(
        entries.map(({ slug }) => slug),
        ['npm-pino'],
      );
    });

    it('only merges main into a pull request that the agent handled', () => {
      const { entries, updates } = plan([pull({ labels: ['ai-assisted'] })]);
      assert.deepStrictEqual(
        updates.map(({ slug, number }) => [slug, number]),
        [['npm-zod', 7]],
      );
      assert.deepStrictEqual(
        entries.map(({ slug }) => slug),
        ['npm-pino'],
      );
    });

    it('replaces a pull request for another version', () => {
      const { entries } = plan([pull({ body: markerOf('npm-zod:0123456789ab') })]);
      assert.strictEqual(entries[0].action, 'replace');
    });

    it('replaces an agent-handled pull request for another version', () => {
      const { entries } = plan([
        pull({ labels: ['human-required'], body: markerOf('npm-zod:0123456789ab') }),
      ]);
      assert.strictEqual(entries[0].action, 'replace');
    });

    it('skips a version that a person closed', () => {
      const closed = plan([], { closedKeys: new Set([zod.key]) });
      assert.deepStrictEqual(
        closed.entries.map(({ slug }) => slug),
        ['npm-pino'],
      );
      assert.strictEqual(closed.skipped[0].reason, 'a person closed this version');
    });
  });

  it('leaves out a candidate that an ignore rule names', () => {
    const { entries, ignored } = buildPlan({
      candidates: [
        candidate('npm', 'zod'),
        { ...candidate('npm', 'eslint'), to: '2.0.0' },
        { ...candidate('npm', 'pino'), to: '2.0.0' },
      ],
      needsPerson: [],
      config: {
        ...config,
        ignore: [
          { name: 'zod', reason: 'Pinned by a person.' },
          { ecosystem: 'npm', name: 'e*', updateTypes: ['major'], reason: 'Wait for the rewrite.' },
        ],
      },
    });
    assert.deepStrictEqual(
      ignored.map(({ name }) => name),
      ['zod', 'eslint'],
    );
    assert.deepStrictEqual(
      entries.map(({ name }) => name),
      ['pino'],
    );
  });

  it('opens a pull request for every new dependency with no limit', () => {
    const { entries } = buildPlan({
      candidates: [
        candidate('npm', 'a'),
        candidate('npm', 'b', true),
        candidate('npm', 'c', true),
        candidate('uv', 'd'),
        candidate('uv', 'e', true),
      ],
      needsPerson: [],
      config,
    });
    assert.deepStrictEqual(entries.map(({ slug }) => slug).sort(), [
      'npm-a',
      'npm-b',
      'npm-c',
      'uv-d',
      'uv-e',
    ]);
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
        needsPerson: [{ ecosystem: 'uv', name: 'fastmcp', reason: 'A limit forbids it.' }],
      },
      'Plan only.',
    );
    assert.match(summary, /Plan only\./);
    assert.match(summary, /### Pull requests for this run \(1\)\n\n- npm zod: 1 -> 2/);
    assert.match(summary, /### Needs a person \(1\)\n\n- uv fastmcp: A limit forbids it\./);
    assert.doesNotMatch(summary, /Skipped/);
  });

  it('lists what is left for the next night', () => {
    const deferred = [
      {
        ecosystem: 'npm',
        name: 'zod',
        isGroup: false,
        action: 'new',
        members: [{ from: '1', to: '2' }],
      },
    ];
    const summary = renderSummary({ entries: [], skipped: [], needsPerson: [], deferred }, '');
    assert.match(
      summary,
      /### Left for the next night \(GitHub allows 256 jobs in a matrix\) \(1\)\n\n- npm zod: 1 -> 2/,
    );
    const none = renderSummary({ entries: [], skipped: [], needsPerson: [] }, '');
    assert.doesNotMatch(none, /next night/);
  });
});
