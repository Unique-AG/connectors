import assert from 'node:assert';
import { describe, it } from 'node:test';
import { applyDocker, createDockerLookup, parseFromLines, planDocker } from './docker.mjs';

const NOW = Date.parse('2026-10-27T00:00:00Z');
const DAY_MS = 24 * 60 * 60 * 1000;
const daysAgo = (days) => new Date(NOW - days * DAY_MS).toISOString();
const digest = (char) => `sha256:${char.repeat(64)}`;
const short = (char) => char.repeat(12);

const dockerfile = (...lines) => `${lines.join('\n')}\nWORKDIR /app\n`;
const NODE_OLD = `FROM node:26.12.1-trixie@${digest('1')} AS base`;
const SLIM_OLD = `FROM node:26.12.1-trixie-slim@${digest('2')} AS runner`;
const PY_A = `FROM python:3.14-slim-trixie@${digest('a')} AS runtime`;
const PY_B = `FROM python:3.14-slim-trixie@${digest('b')} AS builder`;

const nodeTags = [
  { name: '26.12.1-trixie', digest: digest('1'), pushedAt: daysAgo(60) },
  { name: '26.13.0-trixie', digest: digest('3'), pushedAt: daysAgo(20) },
  { name: '26.13.1-trixie', digest: digest('4'), pushedAt: daysAgo(10) },
  { name: '26.14.0-trixie', digest: digest('5'), pushedAt: daysAgo(1) },
  { name: '27.0.0-trixie', digest: digest('6'), pushedAt: daysAgo(10) },
  { name: '26.13.1-trixie-slim', digest: digest('7'), pushedAt: daysAgo(10) },
  { name: '26.13.1-bookworm', digest: digest('8'), pushedAt: daysAgo(10) },
  { name: '26.12.1-trixie-slim', digest: digest('2'), pushedAt: daysAgo(60) },
];
const pythonTags = [
  { name: '3.14-slim-trixie', digest: digest('c'), pushedAt: daysAgo(9) },
  { name: '3.14.1-slim-trixie', digest: digest('d'), pushedAt: daysAgo(9) },
];

const lookupOf = (tagsByImage) => ({
  tags: async (image) => tagsByImage[image] ?? [],
});

const plan = (files, tagsByImage, cooldownDays = 3) =>
  planDocker({ files, lookup: lookupOf(tagsByImage), now: NOW, cooldownDays });

describe('parseFromLines', () => {
  it('reads the image, tag and digest of every pinned line', () => {
    const text = dockerfile(
      NODE_OLD,
      'FROM base AS pruner',
      SLIM_OLD,
      `FROM --platform=linux/amd64 python:3.14-slim-trixie@${digest('a')}`,
    );
    assert.deepStrictEqual(parseFromLines(text), [
      { image: 'node', tag: '26.12.1-trixie', digest: digest('1') },
      { image: 'node', tag: '26.12.1-trixie-slim', digest: digest('2') },
      { image: 'python', tag: '3.14-slim-trixie', digest: digest('a') },
    ]);
  });

  it('skips lines without a digest and stage aliases', () => {
    const text = dockerfile('FROM node:26.12.1-trixie AS base', 'FROM base AS deps', 'RUN echo');
    assert.deepStrictEqual(parseFromLines(text), []);
  });

  it('reads a registry host with a port', () => {
    const text = `FROM localhost:5000/team/app:1.2.3@${digest('e')}\n`;
    assert.deepStrictEqual(parseFromLines(text), [
      { image: 'localhost:5000/team/app', tag: '1.2.3', digest: digest('e') },
    ]);
  });
});

describe('parseFromLines with COPY --from', () => {
  it('reads a COPY --from line, with and without other flags', () => {
    const uv = `ghcr.io/astral-sh/uv:0.12.10@${digest('e')}`;
    const text = dockerfile(
      `COPY --from=${uv} /uv /bin/uv`,
      `COPY --chown=1000:1000 --from=${uv} /uv /bin/uvx`,
      'COPY --from=builder /app /app',
      'COPY . .',
    );
    assert.deepStrictEqual(parseFromLines(text), [
      { image: 'ghcr.io/astral-sh/uv', tag: '0.12.10', digest: digest('e') },
      { image: 'ghcr.io/astral-sh/uv', tag: '0.12.10', digest: digest('e') },
    ]);
  });
});

describe('planDocker', () => {
  it('moves a patch tag to the newest eligible patch of the same suffix and major', async () => {
    const { candidates, needsPerson } = await plan(
      { 'a/Dockerfile': dockerfile(NODE_OLD) },
      { node: nodeTags },
    );
    assert.deepStrictEqual(needsPerson, []);
    assert.deepStrictEqual(candidates, [
      {
        ecosystem: 'docker',
        name: 'node',
        from: `26.12.1-trixie@${short('1')}`,
        to: `26.13.1-trixie@${short('4')}`,
        direct: true,
        data: {
          fromRef: `26.12.1-trixie@${digest('1')}`,
          toRef: `26.13.1-trixie@${digest('4')}`,
        },
      },
    ]);
  });

  it('keeps the suffix exact and does not treat trixie-slim as trixie', async () => {
    const { candidates } = await plan({ 'a/Dockerfile': dockerfile(SLIM_OLD) }, { node: nodeTags });
    assert.deepStrictEqual(
      candidates.map(({ to }) => to),
      [`26.13.1-trixie-slim@${short('7')}`],
    );
  });

  it('ignores a tag pushed inside the cooldown', async () => {
    const { candidates } = await plan(
      { 'a/Dockerfile': dockerfile(NODE_OLD) },
      { node: nodeTags },
      30,
    );
    assert.deepStrictEqual(
      candidates.map(({ to }) => to),
      [],
    );
  });

  it('never jumps to another major', async () => {
    const tags = nodeTags.filter(
      ({ name }) => name === '27.0.0-trixie' || name === '26.12.1-trixie',
    );
    const { candidates } = await plan({ 'a/Dockerfile': dockerfile(NODE_OLD) }, { node: tags });
    assert.deepStrictEqual(candidates, []);
  });

  it('never moves to an older patch', async () => {
    const tags = [
      { name: '26.12.0-trixie', digest: digest('9'), pushedAt: daysAgo(90) },
      { name: '26.12.1-trixie', digest: digest('1'), pushedAt: daysAgo(1) },
    ];
    const { candidates } = await plan({ 'a/Dockerfile': dockerfile(NODE_OLD) }, { node: tags });
    assert.deepStrictEqual(candidates, []);
  });

  it('skips a ref that already points at the target', async () => {
    const current = `FROM node:26.13.1-trixie@${digest('4')} AS base`;
    const { candidates } = await plan({ 'a/Dockerfile': dockerfile(current) }, { node: nodeTags });
    assert.deepStrictEqual(candidates, []);
  });

  it('refreshes the digest of a patch tag that was pushed again', async () => {
    const current = `FROM node:26.13.1-trixie@${digest('0')} AS base`;
    const { candidates } = await plan({ 'a/Dockerfile': dockerfile(current) }, { node: nodeTags });
    assert.deepStrictEqual(
      candidates.map(({ from, to }) => [from, to]),
      [[`26.13.1-trixie@${short('0')}`, `26.13.1-trixie@${short('4')}`]],
    );
  });

  it('keeps a floating tag and refreshes its digest', async () => {
    const { candidates } = await plan({ 'a/Dockerfile': dockerfile(PY_A) }, { python: pythonTags });
    assert.deepStrictEqual(candidates, [
      {
        ecosystem: 'docker',
        name: 'python',
        from: `3.14-slim-trixie@${short('a')}`,
        to: `3.14-slim-trixie@${short('c')}`,
        direct: true,
        data: {
          fromRef: `3.14-slim-trixie@${digest('a')}`,
          toRef: `3.14-slim-trixie@${digest('c')}`,
        },
      },
    ]);
  });

  it('leaves a floating tag alone while it is inside the cooldown', async () => {
    const tags = [{ name: '3.14-slim-trixie', digest: digest('c'), pushedAt: daysAgo(1) }];
    const { candidates } = await plan({ 'a/Dockerfile': dockerfile(PY_A) }, { python: tags });
    assert.deepStrictEqual(candidates, []);
  });

  it('aligns two digests of one floating tag on the same target', async () => {
    const { candidates } = await plan(
      {
        'a/Dockerfile': dockerfile(PY_A),
        'b/Dockerfile': dockerfile(PY_B),
        'c/Dockerfile': dockerfile(PY_A),
      },
      { python: pythonTags },
    );
    assert.deepStrictEqual(
      candidates.map(({ from, to }) => [from, to]),
      [
        [`3.14-slim-trixie@${short('a')}`, `3.14-slim-trixie@${short('c')}`],
        [`3.14-slim-trixie@${short('b')}`, `3.14-slim-trixie@${short('c')}`],
      ],
    );
  });

  it('sends a non-official image to needsPerson', async () => {
    const text = dockerfile(`FROM ghcr.io/astral-sh/uv:0.9.1@${digest('e')} AS uv`);
    const { candidates, needsPerson } = await plan({ 'a/Dockerfile': text }, {});
    assert.deepStrictEqual(candidates, []);
    assert.deepStrictEqual(needsPerson, [
      {
        ecosystem: 'docker',
        name: 'ghcr.io/astral-sh/uv',
        reason: 'Only Docker Hub official images are updated.',
      },
    ]);
  });

  it('sends a COPY --from image to needsPerson', async () => {
    const text = dockerfile(`COPY --from=ghcr.io/astral-sh/uv:0.12.10@${digest('e')} /uv /bin/uv`);
    const { candidates, needsPerson } = await plan({ 'a/Dockerfile': text }, {});
    assert.deepStrictEqual(candidates, []);
    assert.deepStrictEqual(needsPerson, [
      {
        ecosystem: 'docker',
        name: 'ghcr.io/astral-sh/uv',
        reason: 'Only Docker Hub official images are updated.',
      },
    ]);
  });

  describe('digest-only refresh', () => {
    const current = `FROM python:3.14-slim-trixie@${digest('a')} AS runtime`;
    const planWith = (platforms, newPlatforms) =>
      planDocker({
        files: { 'a/Dockerfile': dockerfile(current) },
        lookup: {
          tags: async () => [{ ...pythonTags[0], platforms: newPlatforms }],
          platforms: platforms,
        },
        now: NOW,
        cooldownDays: 3,
      });

    it('produces no candidate when every platform digest is unchanged', async () => {
      const { candidates } = await planWith(
        async () => [digest('1'), digest('2')],
        [digest('1'), digest('2')],
      );
      assert.deepStrictEqual(candidates, []);
    });

    it('keeps the candidate when a platform digest changed', async () => {
      const { candidates } = await planWith(
        async () => [digest('1'), digest('2')],
        [digest('1'), digest('3')],
      );
      assert.strictEqual(candidates.length, 1);
    });

    it('keeps the candidate when the old digest cannot be read', async () => {
      const { candidates, needsPerson } = await planWith(async () => {
        throw new Error('boom');
      }, [digest('1')]);
      assert.strictEqual(candidates.length, 1);
      assert.deepStrictEqual(needsPerson, []);
    });

    it('keeps a tag move even when the platform digests match', async () => {
      const files = { 'a/Dockerfile': dockerfile(NODE_OLD) };
      const tags = nodeTags.map((tag) => ({ ...tag, platforms: [digest('1')] }));
      const { candidates } = await planDocker({
        files,
        lookup: { tags: async () => tags, platforms: async () => [digest('1')] },
        now: NOW,
        cooldownDays: 3,
      });
      assert.strictEqual(candidates.length, 1);
    });
  });

  it('reports a failed lookup and still plans the other images', async () => {
    const lookup = {
      tags: async (image) => {
        if (image === 'node') {
          throw new Error('boom');
        }
        return pythonTags;
      },
    };
    const files = { 'a/Dockerfile': dockerfile(NODE_OLD, PY_A) };
    const { candidates, needsPerson } = await planDocker({
      files,
      lookup,
      now: NOW,
      cooldownDays: 3,
    });
    assert.deepStrictEqual(
      candidates.map(({ name }) => name),
      ['python'],
    );
    assert.deepStrictEqual(needsPerson, [
      { ecosystem: 'docker', name: 'node', reason: 'The tag lookup failed.' },
    ]);
  });
});

describe('applyDocker', () => {
  const candidate = {
    name: 'python',
    data: {
      fromRef: `3.14-slim-trixie@${digest('a')}`,
      toRef: `3.14-slim-trixie@${digest('c')}`,
    },
  };

  it('rewrites a COPY --from line and keeps its flags and paths', () => {
    const uv = {
      name: 'ghcr.io/astral-sh/uv',
      data: { fromRef: `0.12.10@${digest('e')}`, toRef: `0.12.11@${digest('f')}` },
    };
    const text = `COPY --chown=1:1 --from=ghcr.io/astral-sh/uv:0.12.10@${digest('e')} /uv /bin/uv\n`;
    assert.deepStrictEqual(applyDocker({ 'a/Dockerfile': text }, uv), {
      'a/Dockerfile': `COPY --chown=1:1 --from=ghcr.io/astral-sh/uv:0.12.11@${digest('f')} /uv /bin/uv\n`,
    });
  });

  it('rewrites FROM lines and returns only the changed files', () => {
    const files = {
      'a/Dockerfile': dockerfile(PY_A, 'FROM base AS x'),
      'b/Dockerfile': dockerfile(PY_B),
      'c/Dockerfile': dockerfile(NODE_OLD),
    };
    const changed = applyDocker(files, candidate);
    assert.deepStrictEqual(Object.keys(changed), ['a/Dockerfile']);
    assert.strictEqual(
      changed['a/Dockerfile'],
      dockerfile(`FROM python:3.14-slim-trixie@${digest('c')} AS runtime`, 'FROM base AS x'),
    );
  });

  it('does not mutate its argument and is idempotent', () => {
    const files = { 'a/Dockerfile': dockerfile(PY_A) };
    const snapshot = structuredClone(files);
    const first = applyDocker(files, candidate);
    assert.deepStrictEqual(files, snapshot);
    assert.deepStrictEqual(applyDocker(first, candidate), {});
    assert.deepStrictEqual(applyDocker(files, candidate), first);
  });

  it('leaves a ref that appears outside a FROM line untouched', () => {
    const text = `# python:${candidate.data.fromRef}\nENV X=python:${candidate.data.fromRef}\n`;
    assert.deepStrictEqual(applyDocker({ 'a/Dockerfile': text }, candidate), {});
  });

  it('keeps the platform flag and Windows line endings', () => {
    const text = `FROM --platform=linux/amd64 python:${candidate.data.fromRef} AS runtime\r\nRUN x\r\n`;
    const changed = applyDocker({ 'a/Dockerfile': text }, candidate);
    assert.strictEqual(
      changed['a/Dockerfile'],
      `FROM --platform=linux/amd64 python:${candidate.data.toRef} AS runtime\r\nRUN x\r\n`,
    );
  });
});

describe('createDockerLookup', () => {
  const answer = (body, status = 200) => ({ status, json: async () => body });

  it('follows next links and maps the Docker Hub fields', async () => {
    const urls = [];
    const pages = [
      answer({
        next: 'https://hub.docker.com/v2/repositories/library/node/tags?page=2',
        results: [
          {
            name: '26.1.0',
            digest: digest('1'),
            tag_last_pushed: daysAgo(5),
            last_updated: daysAgo(9),
          },
        ],
      }),
      answer({
        next: null,
        results: [{ name: '26.0.0', digest: digest('2'), last_updated: daysAgo(30) }],
      }),
    ];
    const fetchImpl = async (url, options) => {
      urls.push(url);
      assert.ok(options.signal instanceof AbortSignal);
      return pages[urls.length - 1];
    };
    const tags = await createDockerLookup(fetchImpl).tags('node');
    assert.deepStrictEqual(urls, [
      'https://hub.docker.com/v2/repositories/library/node/tags?page_size=100&ordering=last_updated',
      'https://hub.docker.com/v2/repositories/library/node/tags?page=2',
    ]);
    assert.deepStrictEqual(tags, [
      { name: '26.1.0', digest: digest('1'), pushedAt: daysAgo(5), platforms: [] },
      { name: '26.0.0', digest: digest('2'), pushedAt: daysAgo(30), platforms: [] },
    ]);
  });

  it('reads images[0].digest when the tag has no top-level digest', async () => {
    const fetchImpl = async () =>
      answer({
        next: null,
        results: [
          { name: '1.0', images: [{ digest: digest('3') }], last_updated: daysAgo(4) },
          { name: '0.9', last_updated: daysAgo(4) },
        ],
      });
    assert.deepStrictEqual(await createDockerLookup(fetchImpl).tags('node'), [
      { name: '1.0', digest: digest('3'), pushedAt: daysAgo(4), platforms: [digest('3')] },
    ]);
  });

  it('returns an empty list when the repository is not found', async () => {
    const fetchImpl = async () => answer({}, 404);
    assert.deepStrictEqual(await createDockerLookup(fetchImpl).tags('node'), []);
  });

  it('throws on a rate limit or a server error', async () => {
    for (const status of [429, 500, 503]) {
      const fetchImpl = async () => answer({}, status);
      await assert.rejects(createDockerLookup(fetchImpl).tags('node'), new RegExp(`${status}`));
    }
  });

  it('lists the real platform digests of the tag, without attestations', async () => {
    const fetchImpl = async () =>
      answer({
        next: null,
        results: [
          {
            name: '1.0',
            digest: digest('3'),
            images: [
              { digest: digest('b'), architecture: 'arm64' },
              { digest: digest('a'), architecture: 'amd64' },
              { digest: digest('c'), architecture: 'unknown' },
            ],
            last_updated: daysAgo(4),
          },
        ],
      });
    const [tag] = await createDockerLookup(fetchImpl).tags('node');
    assert.deepStrictEqual(tag.platforms, [digest('a'), digest('b')]);
  });

  it('reads the platform digests of an old digest with an anonymous token', async () => {
    const calls = [];
    const fetchImpl = async (url, options) => {
      calls.push({ url, headers: options.headers });
      return new URL(url).host === 'auth.docker.io'
        ? answer({ token: 'tkn' })
        : answer({
            manifests: [
              { digest: digest('b'), platform: { architecture: 'arm64' } },
              { digest: digest('a'), platform: { architecture: 'amd64' } },
              { digest: digest('c'), platform: { architecture: 'unknown' } },
            ],
          });
    };
    assert.deepStrictEqual(await createDockerLookup(fetchImpl).platforms('node', digest('9')), [
      digest('a'),
      digest('b'),
    ]);
    assert.deepStrictEqual(
      calls.map(({ url }) => url),
      [
        'https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/node:pull',
        `https://registry-1.docker.io/v2/library/node/manifests/${digest('9')}`,
      ],
    );
    assert.strictEqual(calls[1].headers.Authorization, 'Bearer tkn');
    assert.match(calls[1].headers.Accept, /application\/vnd\.oci\.image\.index\.v1\+json/);
  });

  it('stops after ten pages', async () => {
    let calls = 0;
    const fetchImpl = async () => {
      calls++;
      return answer({
        next: `https://hub.docker.com/v2/repositories/library/node/tags?page=${calls + 1}`,
        results: [{ name: `1.0.${calls}`, digest: digest('4'), last_updated: daysAgo(4) }],
      });
    };
    const tags = await createDockerLookup(fetchImpl).tags('node');
    assert.strictEqual(calls, 10);
    assert.strictEqual(tags.length, 10);
  });
});
