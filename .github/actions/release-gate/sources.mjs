const REQUEST_TIMEOUT_MS = 10_000;
const MAX_COMMENT_PAGES = 10;

const isRetryable = (status) => status === 429 || status >= 500;

async function getJson(url, fetchImpl, headers = {}) {
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const response = await fetchImpl(url, {
        headers,
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      });
      if (response.ok) {
        return await response.json();
      }
      if (!isRetryable(response.status)) {
        return null;
      }
    } catch {}
  }
  return null;
}

export function createRegistryLookups(fetchImpl = fetch) {
  const npmDocuments = new Map();
  const npmDocument = (name) => {
    if (!npmDocuments.has(name)) {
      npmDocuments.set(
        name,
        getJson(`https://registry.npmjs.org/${encodeURIComponent(name)}`, fetchImpl),
      );
    }
    return npmDocuments.get(name);
  };
  return {
    'python-pkg': async (name, version) => {
      const payload = await getJson(
        `https://pypi.org/pypi/${encodeURIComponent(name)}/${encodeURIComponent(version)}/json`,
        fetchImpl,
      );
      const uploads = Array.isArray(payload?.urls)
        ? payload.urls
            .map((file) => file.upload_time_iso_8601)
            .filter((time) => typeof time === 'string')
        : [];
      return uploads.sort()[0] ?? null;
    },
    'node-pkg': async (name, version) => {
      const payload = await npmDocument(name);
      const published = payload?.time?.[version];
      return typeof published === 'string' ? published : null;
    },
  };
}

const githubHeaders = (token) => ({
  Accept: 'application/vnd.github+json',
  Authorization: `Bearer ${token}`,
  'X-GitHub-Api-Version': '2022-11-28',
});

export async function listComments({
  apiUrl,
  repository,
  pullRequestNumber,
  token,
  fetchImpl = fetch,
}) {
  const found = [];
  for (let page = 1; page <= MAX_COMMENT_PAGES; page++) {
    const url = `${apiUrl}/repos/${repository}/issues/${pullRequestNumber}/comments?per_page=100&page=${page}`;
    const response = await fetchImpl(url, {
      headers: githubHeaders(token),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
    if (!response.ok) {
      throw new Error(`GitHub comments request failed with HTTP ${response.status}`);
    }
    const comments = await response.json();
    found.push(...comments.map((comment) => ({ id: comment.id, body: comment.body ?? '' })));
    if (comments.length < 100) {
      return found;
    }
  }
  throw new Error('GitHub comments response exceeded the pagination limit');
}

export async function upsertComment({
  apiUrl,
  repository,
  pullRequestNumber,
  token,
  marker,
  build,
  fetchImpl = fetch,
}) {
  const comments = await listComments({ apiUrl, repository, pullRequestNumber, token, fetchImpl });
  const existing = comments.find((comment) => comment.body.startsWith(marker));
  const url = existing
    ? `${apiUrl}/repos/${repository}/issues/comments/${existing.id}`
    : `${apiUrl}/repos/${repository}/issues/${pullRequestNumber}/comments`;
  const response = await fetchImpl(url, {
    method: existing ? 'PATCH' : 'POST',
    headers: { ...githubHeaders(token), 'Content-Type': 'application/json' },
    body: JSON.stringify({ body: build(existing?.body) }),
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  if (!response.ok) {
    throw new Error(`GitHub comment write failed with HTTP ${response.status}`);
  }
}
