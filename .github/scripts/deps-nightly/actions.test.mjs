import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import {
  applyActions,
  createActionsLookup,
  parseActionUses,
  planActions as planWithLedger,
} from './actions.mjs';

const NOW = Date.parse('2026-10-27T00:00:00Z');
const sha = (character) => character.repeat(40);
const OLD_SHA = sha('a');
const NEW_SHA = sha('b');
const release = (tag, publishedAt) => ({ tag, publishedAt });
const DAY_MS = 24 * 60 * 60 * 1000;
const seen = (shas, daysAgo) =>
  Object.fromEntries(
    Object.entries(shas).map(([key, value]) => [
      key,
      { sha: value, firstSeen: NOW - daysAgo * DAY_MS },
    ]),
  );
const planActions = (options) =>
  planWithLedger({ ledger: seen(options.lookup.shas, 10), ...options });

const WORKFLOW = [
  'jobs:',
  '  build:',
  '    steps:',
  `      - uses: actions/checkout@${OLD_SHA} # v7.0.1`,
  `        uses: github/codeql-action/upload-sarif@${OLD_SHA} # v4.38.3`,
  `      - uses: unique-ag/actions/github/policies/verify-pinned-actions@${OLD_SHA} # main`,
  `      - uses: ./.github/actions/local`,
  `      - uses: docker://alpine:3.20`,
  `      # uses: actions/checkout@${OLD_SHA} # v1.0.0`,
  `      - uses: actions/cache@${OLD_SHA}`,
].join('\n');

function fakeLookup({ releases, shas = {}, failing = [] }) {
  return {
    shas,
    async releases(repo) {
      assert.ok(!failing.includes(repo), `lookup failed for ${repo}`);
      return releases[repo] ?? [];
    },
    async commitSha(repo, tag) {
      return shas[`${repo}@${tag}`] ?? null;
    },
  };
}

describe('parseActionUses', () => {
  it('reads repo, subpath, sha and tag from the real shapes', () => {
    assert.deepEqual(parseActionUses(WORKFLOW), [
      { repo: 'actions/checkout', path: '', sha: OLD_SHA, tag: 'v7.0.1' },
      { repo: 'github/codeql-action', path: 'upload-sarif', sha: OLD_SHA, tag: 'v4.38.3' },
      {
        repo: 'unique-ag/actions',
        path: 'github/policies/verify-pinned-actions',
        sha: OLD_SHA,
        tag: 'main',
      },
      { repo: 'actions/cache', path: '', sha: OLD_SHA, tag: '' },
    ]);
  });

  it('returns an empty list for text without uses', () => {
    assert.deepEqual(parseActionUses('name: test\non: push\n'), []);
  });
});

describe('planActions', () => {
  const files = {
    'a.yaml': `      - uses: actions/checkout@${OLD_SHA} # v7.0.1\n`,
    'b.yaml': [
      `      uses: actions/checkout@${OLD_SHA} # v7.0.1`,
      `      uses: github/codeql-action/init@${OLD_SHA} # v4.38.3`,
      `      uses: github/codeql-action/upload-sarif@${OLD_SHA} # v4.38.3`,
    ].join('\n'),
  };
  const plan = (overrides) =>
    planActions({
      files,
      now: NOW,
      cooldownDays: 3,
      lookup: fakeLookup({
        releases: {
          'actions/checkout': [
            release('v7.0.2', '2026-10-20T00:00:00Z'),
            release('v7.0.1', '2026-09-01T00:00:00Z'),
          ],
          'github/codeql-action': [release('v4.38.3', '2026-09-01T00:00:00Z')],
        },
        shas: { 'actions/checkout@v7.0.2': NEW_SHA },
      }),
      ...overrides,
    });

  it('groups every use of one repo into one candidate', async () => {
    const { candidates, needsPerson } = await plan();
    assert.deepEqual(candidates, [
      {
        ecosystem: 'actions',
        name: 'actions/checkout',
        from: 'v7.0.1',
        to: 'v7.0.2',
        direct: true,
        data: { toSha: NEW_SHA, major: false },
      },
    ]);
    assert.deepEqual(needsPerson, []);
  });

  it('picks the previous release when the newest is inside the cooldown', async () => {
    const { candidates } = await planActions({
      files,
      now: NOW,
      cooldownDays: 3,
      lookup: fakeLookup({
        releases: {
          'actions/checkout': [
            release('v7.0.3', '2026-10-25T00:00:00Z'),
            release('v7.0.2', '2026-10-20T00:00:00Z'),
          ],
        },
        shas: { 'actions/checkout@v7.0.2': NEW_SHA, 'actions/checkout@v7.0.3': sha('c') },
      }),
    });
    assert.equal(candidates[0].to, 'v7.0.2');
  });

  it('skips unstable tags and picks the newest stable release', async () => {
    const { candidates } = await planActions({
      files: { 'a.yaml': files['a.yaml'] },
      now: NOW,
      cooldownDays: 3,
      lookup: fakeLookup({
        releases: {
          'actions/checkout': [
            release('v8.0.0-rc.1', '2026-10-01T00:00:00Z'),
            release('v7.1.0', '2026-10-01T00:00:00Z'),
            release('latest', '2026-10-01T00:00:00Z'),
          ],
        },
        shas: { 'actions/checkout@v7.1.0': NEW_SHA },
      }),
    });
    assert.equal(candidates[0].to, 'v7.1.0');
  });

  it('sets major when the first number changes', async () => {
    const { candidates } = await planActions({
      files: { 'a.yaml': files['a.yaml'] },
      now: NOW,
      cooldownDays: 3,
      lookup: fakeLookup({
        releases: { 'actions/checkout': [release('v8.0.0', '2026-10-01T00:00:00Z')] },
        shas: { 'actions/checkout@v8.0.0': NEW_SHA },
      }),
    });
    assert.equal(candidates[0].data.major, true);
  });

  it('skips a repo that is already at the newest eligible release', async () => {
    const { candidates, needsPerson } = await plan({
      files: { 'a.yaml': `uses: actions/checkout@${OLD_SHA} # v7.0.2\n` },
    });
    assert.deepEqual(candidates, []);
    assert.deepEqual(needsPerson, []);
  });

  it('skips a repo that is ahead of the newest eligible release', async () => {
    const { candidates } = await plan({
      files: { 'a.yaml': `uses: actions/checkout@${OLD_SHA} # v7.5.0\n` },
    });
    assert.deepEqual(candidates, []);
  });

  it('aligns mixed tags in two files to one tag', async () => {
    const { candidates } = await plan({
      files: {
        'a.yaml': `uses: actions/checkout@${OLD_SHA} # v7.0.1\n`,
        'b.yaml': `uses: actions/checkout@${NEW_SHA} # v7.0.2\n`,
      },
    });
    assert.equal(candidates.length, 1);
    assert.equal(candidates[0].from, 'v7.0.1');
    assert.equal(candidates[0].to, 'v7.0.2');
    assert.equal(candidates[0].data.major, false);
  });

  it('sends a branch pin and a missing comment to needsPerson', async () => {
    const { candidates, needsPerson } = await plan({ files: { 'a.yaml': WORKFLOW } });
    assert.deepEqual(
      needsPerson.map(({ name }) => name).sort(),
      ['actions/cache', 'unique-ag/actions'].sort(),
    );
    assert.match(needsPerson.find(({ name }) => name === 'unique-ag/actions').reason, /main/);
    assert.ok(candidates.every(({ name }) => name !== 'unique-ag/actions'));
  });

  it('sends a repo with no eligible release to needsPerson', async () => {
    const { candidates, needsPerson } = await plan({
      files: { 'a.yaml': files['a.yaml'] },
      lookup: fakeLookup({
        releases: { 'actions/checkout': [release('v7.0.2', '2026-10-26T00:00:00Z')] },
      }),
    });
    assert.deepEqual(candidates, []);
    assert.equal(needsPerson[0].name, 'actions/checkout');
  });

  it('sends a repo with no commit sha to needsPerson', async () => {
    const { candidates, needsPerson } = await plan({
      files: { 'a.yaml': files['a.yaml'] },
      lookup: fakeLookup({
        releases: { 'actions/checkout': [release('v7.0.2', '2026-10-01T00:00:00Z')] },
      }),
    });
    assert.deepEqual(candidates, []);
    assert.deepEqual(needsPerson, [
      {
        ecosystem: 'actions',
        name: 'actions/checkout',
        reason: 'The lookup found no commit for v7.0.2.',
      },
    ]);
  });

  it('keeps going when the lookup throws for one repo', async () => {
    const { candidates, needsPerson } = await plan({
      lookup: fakeLookup({
        releases: {
          'github/codeql-action': [release('v4.39.0', '2026-10-01T00:00:00Z')],
        },
        shas: { 'github/codeql-action@v4.39.0': NEW_SHA },
        failing: ['actions/checkout'],
      }),
    });
    assert.deepEqual(
      candidates.map(({ name }) => name),
      ['github/codeql-action'],
    );
    assert.equal(needsPerson.length, 1);
    assert.equal(needsPerson[0].name, 'actions/checkout');
    assert.match(needsPerson[0].reason, /^The lookup failed\./);
  });
});

describe('applyActions', () => {
  const change = { name: 'github/codeql-action', to: 'v4.39.0', data: { toSha: NEW_SHA } };
  const files = {
    'a.yaml': [
      `      - uses: github/codeql-action/upload-sarif@${OLD_SHA} # v4.38.3`,
      `        uses: github/codeql-action/init@${OLD_SHA} # v4.38.3 keep this`,
      `      - uses: actions/checkout@${OLD_SHA} # v7.0.1`,
    ].join('\n'),
    'b.yaml': `      - uses: actions/checkout@${OLD_SHA} # v7.0.1\n`,
    'c.yaml': `uses: github/codeql-action/analyze@${OLD_SHA}\n`,
  };

  it('rewrites sha and comment and keeps indentation, subpath and trailing text', () => {
    const result = applyActions(files, change);
    assert.deepEqual(result, {
      'a.yaml': [
        `      - uses: github/codeql-action/upload-sarif@${NEW_SHA} # v4.39.0`,
        `        uses: github/codeql-action/init@${NEW_SHA} # v4.39.0 keep this`,
        `      - uses: actions/checkout@${OLD_SHA} # v7.0.1`,
      ].join('\n'),
      'c.yaml': `uses: github/codeql-action/analyze@${NEW_SHA} # v4.39.0\n`,
    });
  });

  it('returns only the changed files', () => {
    assert.deepEqual(Object.keys(applyActions(files, change)), ['a.yaml', 'c.yaml']);
  });

  it('does not change its argument', () => {
    const snapshot = structuredClone(files);
    applyActions(files, change);
    assert.deepEqual(files, snapshot);
  });

  it('is idempotent', () => {
    const once = applyActions(files, change);
    assert.deepEqual(applyActions({ ...files, ...once }, change), {});
  });

  it('rejects a sha that is not a full commit sha', () => {
    assert.throws(
      () => applyActions(files, { ...change, data: { toSha: 'abc' } }),
      /Not a full commit SHA/,
    );
  });
});

describe('planActions ledger', () => {
  const files = { 'a.yaml': `      - uses: actions/checkout@${OLD_SHA} # v7.0.1` };
  const lookup = fakeLookup({
    releases: {
      'actions/checkout': [
        release('v7.0.2', '2026-10-20T00:00:00Z'),
        release('v7.0.1', '2026-09-01T00:00:00Z'),
      ],
    },
    shas: { 'actions/checkout@v7.0.1': OLD_SHA, 'actions/checkout@v7.0.2': NEW_SHA },
  });
  const run = (ledger) => planWithLedger({ files, lookup, now: NOW, cooldownDays: 3, ledger });

  it('records a tag on first sight and proposes nothing yet', async () => {
    const result = await run({});
    assert.deepEqual(result.candidates, []);
    assert.deepEqual(result.ledger['actions/checkout@v7.0.2'], { sha: NEW_SHA, firstSeen: NOW });
  });

  it('waits until the same commit has been seen for the cooldown', async () => {
    const ledger = seen(lookup.shas, 1);
    const result = await run(ledger);
    assert.deepEqual(result.candidates, []);
    assert.deepEqual(result.ledger, {
      'actions/checkout@v7.0.2': ledger['actions/checkout@v7.0.2'],
    });
  });

  it('pins the commit that the job saw, once it has been stable for the cooldown', async () => {
    const result = await run(seen(lookup.shas, 4));
    assert.equal(result.candidates[0].data.toSha, NEW_SHA);
  });

  it('flags a tag that moved to another commit and keeps the first commit on record', async () => {
    const ledger = seen({ ...lookup.shas, 'actions/checkout@v7.0.2': sha('c') }, 10);
    const result = await run(ledger);
    assert.deepEqual(result.candidates, []);
    assert.match(result.needsPerson[0].reason, /v7\.0\.2 points to a new commit/);
    assert.equal(result.ledger['actions/checkout@v7.0.2'].sha, sha('c'));
  });

  it('keeps the old records of a repo when the lookup fails', async () => {
    const ledger = seen(lookup.shas, 10);
    const result = await planWithLedger({
      files,
      lookup: fakeLookup({ releases: {}, failing: ['actions/checkout'] }),
      now: NOW,
      cooldownDays: 3,
      ledger,
    });
    assert.deepEqual(result.ledger, ledger);
  });
});

describe('createActionsLookup', () => {
  const respond = (status, body) => ({ status, json: async () => body });
  const record = (answer) => {
    const calls = [];
    const fetchImpl = async (url, init) => {
      calls.push({ url, init });
      return answer(url);
    };
    return { calls, fetchImpl };
  };

  it('lists releases without drafts and prereleases', async () => {
    const { calls, fetchImpl } = record(() =>
      respond(200, [
        {
          tag_name: 'v2.0.0',
          published_at: '2026-10-01T00:00:00Z',
          draft: false,
          prerelease: false,
        },
        {
          tag_name: 'v3.0.0-rc1',
          published_at: '2026-10-02T00:00:00Z',
          draft: false,
          prerelease: true,
        },
        {
          tag_name: 'v3.0.0',
          published_at: '2026-10-03T00:00:00Z',
          draft: true,
          prerelease: false,
        },
      ]),
    );
    const lookup = createActionsLookup('secret', fetchImpl);
    assert.deepEqual(await lookup.releases('actions/checkout'), [
      { tag: 'v2.0.0', publishedAt: '2026-10-01T00:00:00Z' },
    ]);
    assert.equal(
      calls[0].url,
      'https://api.github.com/repos/actions/checkout/releases?per_page=30',
    );
    assert.deepEqual(calls[0].init.headers, {
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      Authorization: 'Bearer secret',
    });
    assert.ok(calls[0].init.signal instanceof AbortSignal);
  });

  it('reads the commit sha of a tag', async () => {
    const { calls, fetchImpl } = record(() => respond(200, { sha: NEW_SHA }));
    const lookup = createActionsLookup(undefined, fetchImpl);
    assert.equal(await lookup.commitSha('actions/checkout', 'v7.0.2'), NEW_SHA);
    assert.equal(calls[0].url, 'https://api.github.com/repos/actions/checkout/commits/v7.0.2');
    assert.equal('Authorization' in calls[0].init.headers, false);
  });

  it('returns an empty list and null for a non-200 answer', async () => {
    const lookup = createActionsLookup('secret', async () =>
      respond(404, { message: 'Not Found' }),
    );
    assert.deepEqual(await lookup.releases('actions/missing'), []);
    assert.equal(await lookup.commitSha('actions/missing', 'v1.0.0'), null);
  });
});
