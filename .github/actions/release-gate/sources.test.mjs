import assert from 'node:assert/strict';
import test from 'node:test';
import { createRegistryLookups, listComments } from './sources.mjs';

const jsonResponse = (payload, status = 200) => new Response(JSON.stringify(payload), { status });

test('reads the earliest upload time from the PyPI release payload', async () => {
  const fetchImpl = async (url) => {
    assert.equal(url, 'https://pypi.org/pypi/urllib3/1.26.19/json');
    return jsonResponse({
      urls: [
        { upload_time_iso_8601: '2026-10-12T10:00:00.000000Z' },
        { upload_time_iso_8601: '2026-10-11T09:00:00.000000Z' },
      ],
    });
  };
  const lookups = createRegistryLookups(fetchImpl);
  assert.equal(await lookups['python-pkg']('urllib3', '1.26.19'), '2026-10-11T09:00:00.000000Z');
});

test('reads the version time from the npm payload', async () => {
  const fetchImpl = async (url) => {
    assert.equal(url, 'https://registry.npmjs.org/%40scope%2Fpkg');
    return jsonResponse({ time: { '1.0.0': '2026-10-01T00:00:00.000Z' } });
  };
  const lookups = createRegistryLookups(fetchImpl);
  assert.equal(await lookups['node-pkg']('@scope/pkg', '1.0.0'), '2026-10-01T00:00:00.000Z');
  assert.equal(await lookups['node-pkg']('@scope/pkg', '9.9.9'), null);
});

test('returns null when the registry fails', async () => {
  const lookups = createRegistryLookups(async () => jsonResponse({}, 404));
  assert.equal(await lookups['python-pkg']('urllib3', '1.0'), null);
  const broken = createRegistryLookups(async () => {
    throw new Error('network down');
  });
  assert.equal(await broken['node-pkg']('tar', '1.0.0'), null);
});

test('collects comments across pages with author, link and time', async () => {
  const pages = [
    Array.from({ length: 100 }, () => ({ body: 'a' })),
    [
      {
        body: 'Security exception approved by: Alice for abc1234',
        user: { login: 'alice' },
        html_url: 'https://github.com/unique-ag/connectors/pull/7#issuecomment-1',
        created_at: '2026-10-27T10:00:00Z',
      },
    ],
  ];
  const urls = [];
  const fetchImpl = async (url, request) => {
    urls.push(url);
    assert.equal(request.headers.Authorization, 'Bearer token');
    return jsonResponse(pages[urls.length - 1]);
  };
  const comments = await listComments({
    apiUrl: 'https://api.github.com',
    repository: 'unique-ag/connectors',
    pullRequestNumber: '7',
    token: 'token',
    fetchImpl,
  });
  assert.equal(comments.length, 101);
  assert.deepEqual(comments.at(-1), {
    body: 'Security exception approved by: Alice for abc1234',
    author: 'alice',
    url: 'https://github.com/unique-ag/connectors/pull/7#issuecomment-1',
    createdAt: '2026-10-27T10:00:00Z',
  });
  assert.deepEqual(comments[0], { body: 'a', author: 'unknown', url: '', createdAt: '' });
  assert.match(urls[1], /issues\/7\/comments\?per_page=100&page=2$/);
});

test('throws when the comments request fails', async () => {
  await assert.rejects(
    listComments({
      apiUrl: 'https://api.github.com',
      repository: 'unique-ag/connectors',
      pullRequestNumber: '7',
      token: 'token',
      fetchImpl: async () => jsonResponse({}, 403),
    }),
    /HTTP 403/,
  );
});
