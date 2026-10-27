import assert from 'node:assert/strict';
import test from 'node:test';
import { createRegistryLookups, listComments, upsertComment } from './sources.mjs';

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

test('collects comments across pages', async () => {
  const pages = [
    Array.from({ length: 100 }, (_, index) => ({ id: index, body: 'a' })),
    [{ id: 500, body: '<!-- release-gate-exception -->' }],
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
  assert.deepEqual(comments.at(-1), { id: 500, body: '<!-- release-gate-exception -->' });
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

const upsert = (fetchImpl, build = () => 'new body') =>
  upsertComment({
    apiUrl: 'https://api.github.com',
    repository: 'unique-ag/connectors',
    pullRequestNumber: '7',
    token: 'token',
    marker: '<!-- marker -->',
    build,
    fetchImpl,
  });

test('creates the comment when none has the marker', async () => {
  const calls = [];
  await upsert(async (url, request) => {
    calls.push({ url, method: request.method, body: request.body });
    return request.method ? jsonResponse({}, 201) : jsonResponse([{ id: 1, body: 'other' }]);
  });
  assert.equal(calls[1].method, 'POST');
  assert.match(calls[1].url, /issues\/7\/comments$/);
  assert.equal(JSON.parse(calls[1].body).body, 'new body');
});

test('updates the comment in place and passes the old body to the builder', async () => {
  const calls = [];
  let received;
  await upsert(
    async (url, request) => {
      calls.push({ url, method: request.method });
      return request.method
        ? jsonResponse({})
        : jsonResponse([{ id: 42, body: '<!-- marker -->\n- old' }]);
    },
    (existingBody) => {
      received = existingBody;
      return 'updated';
    },
  );
  assert.equal(received, '<!-- marker -->\n- old');
  assert.equal(calls[1].method, 'PATCH');
  assert.match(calls[1].url, /issues\/comments\/42$/);
});

test('throws when the comment write fails', async () => {
  await assert.rejects(
    upsert(async (_url, request) => (request.method ? jsonResponse({}, 403) : jsonResponse([]))),
    /write failed with HTTP 403/,
  );
});
