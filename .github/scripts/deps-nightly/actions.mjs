import assert from 'node:assert';
import { compareVersions, isStable, newestVersion, oldestVersion } from './versions.mjs';

const DAY_MS = 24 * 60 * 60 * 1000;
const API = 'https://api.github.com';
const REQUEST_TIMEOUT_MS = 30_000;
const FULL_SHA = /^[0-9a-f]{40}$/;
const USES = /^(\s*(?:-\s+)?uses:\s*)([^\s@]+)@([0-9a-f]{40})(?:\s+#\s*(\S*))?(.*)$/;

function matchUses(line) {
  const match = USES.exec(line);
  return match && !match[2].startsWith('.') && !match[2].startsWith('docker://') ? match : null;
}

function splitReference(reference) {
  const [owner, repo, ...path] = reference.split('/');
  return { repo: `${owner}/${repo}`, path: path.join('/') };
}

export function parseActionUses(text) {
  return text.split('\n').flatMap((line) => {
    const match = matchUses(line);
    return match ? [{ ...splitReference(match[2]), sha: match[3], tag: match[4] ?? '' }] : [];
  });
}

function needsPerson(name, reason) {
  return { needsPerson: { ecosystem: 'actions', name, reason } };
}

async function planRepo({ repo, uses, lookup, cutoff }) {
  const unpinned = uses.find(({ tag }) => !isStable(tag));
  if (unpinned) {
    return needsPerson(
      repo,
      unpinned.tag
        ? `A use is pinned to ${unpinned.tag}. This is not a release.`
        : 'A use has no version comment.',
    );
  }
  try {
    const eligible = (await lookup.releases(repo))
      .filter(({ tag, publishedAt }) => isStable(tag) && Date.parse(publishedAt) <= cutoff)
      .map(({ tag }) => tag);
    if (eligible.length === 0) {
      return needsPerson(repo, 'No stable release is old enough.');
    }
    const tags = uses.map(({ tag }) => tag);
    const to = newestVersion(eligible);
    const newestCurrent = newestVersion(tags);
    if (
      compareVersions(to, newestCurrent) < 0 ||
      tags.every((tag) => compareVersions(tag, to) === 0)
    ) {
      return {};
    }
    const toSha = await lookup.commitSha(repo, to);
    if (!FULL_SHA.test(toSha ?? '')) {
      return needsPerson(repo, `The lookup found no commit for ${to}.`);
    }
    return {
      candidate: {
        ecosystem: 'actions',
        name: repo,
        from: oldestVersion(tags),
        to,
        direct: true,
        data: { toSha, major: /\d+/.exec(to)[0] !== /\d+/.exec(newestCurrent)[0] },
      },
    };
  } catch (error) {
    return needsPerson(
      repo,
      `The lookup failed. ${error instanceof Error ? error.message : String(error)}`,
    );
  }
}

export async function planActions({ files, lookup, now, cooldownDays }) {
  const cutoff = now - cooldownDays * DAY_MS;
  const byRepo = Map.groupBy(
    Object.values(files).flatMap((text) => parseActionUses(text)),
    ({ repo }) => repo,
  );
  const results = await Promise.all(
    [...byRepo].map(([repo, uses]) => planRepo({ repo, uses, lookup, cutoff })),
  );
  return {
    candidates: results.flatMap(({ candidate }) => candidate ?? []),
    needsPerson: results.flatMap((result) => result.needsPerson ?? []),
  };
}

export function applyActions(files, { name, to, data }) {
  assert.match(data.toSha, FULL_SHA, `Not a full commit SHA: ${data.toSha}`);
  const rewrite = (line) => {
    const match = matchUses(line);
    return match && splitReference(match[2]).repo === name
      ? `${match[1]}${match[2]}@${data.toSha} # ${to}${match[5]}`
      : line;
  };
  return Object.fromEntries(
    Object.entries(files).flatMap(([path, text]) => {
      const updated = text.split('\n').map(rewrite).join('\n');
      return updated === text ? [] : [[path, updated]];
    }),
  );
}

export function createActionsLookup(token, fetchImpl = fetch) {
  const headers = {
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  const get = async (path) => {
    const response = await fetchImpl(`${API}/repos/${path}`, {
      headers,
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
    return response.status === 200 ? response.json() : null;
  };
  return {
    async releases(repo) {
      const body = await get(`${repo}/releases?per_page=30`);
      return (body ?? [])
        .filter(({ draft, prerelease }) => !draft && !prerelease)
        .map(({ tag_name, published_at }) => ({ tag: tag_name, publishedAt: published_at }));
    },
    async commitSha(repo, tag) {
      const body = await get(`${repo}/commits/${tag}`);
      return body?.sha ?? null;
    },
  };
}
