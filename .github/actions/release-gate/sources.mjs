const REQUEST_TIMEOUT_MS = 10_000;
const MAX_COMMENT_PAGES = 10;

async function getJson(url, fetchImpl, headers = {}) {
  try {
    const response = await fetchImpl(url, {
      headers,
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

export function createRegistryLookups(fetchImpl = fetch) {
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
      const payload = await getJson(
        `https://registry.npmjs.org/${encodeURIComponent(name)}`,
        fetchImpl,
      );
      const published = payload?.time?.[version];
      return typeof published === 'string' ? published : null;
    },
  };
}

export async function listCommentBodies({
  apiUrl,
  repository,
  pullRequestNumber,
  token,
  fetchImpl = fetch,
}) {
  const bodies = [];
  for (let page = 1; page <= MAX_COMMENT_PAGES; page++) {
    const url = `${apiUrl}/repos/${repository}/issues/${pullRequestNumber}/comments?per_page=100&page=${page}`;
    const response = await fetchImpl(url, {
      headers: {
        Accept: 'application/vnd.github+json',
        Authorization: `Bearer ${token}`,
        'X-GitHub-Api-Version': '2022-11-28',
      },
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
    if (!response.ok) {
      throw new Error(`GitHub comments request failed with HTTP ${response.status}`);
    }
    const comments = await response.json();
    bodies.push(...comments.map((comment) => comment.body ?? ''));
    if (comments.length < 100) {
      return bodies;
    }
  }
  throw new Error('GitHub comments response exceeded the pagination limit');
}
