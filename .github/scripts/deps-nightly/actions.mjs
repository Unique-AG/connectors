import assert from 'node:assert';
import { compareVersions, isStable, newestVersion, oldestVersion } from './versions.mjs';

const DAY_MS = 24 * 60 * 60 * 1000;
const API = 'https://api.github.com';
const REQUEST_TIMEOUT_MS = 30_000;
const MAX_TAG_FALLBACK = 10;
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

async function planRepo({ repo, uses, lookup, cutoff, ledger, now }) {
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
    const stable = (await lookup.releases(repo)).filter(({ tag }) => isStable(tag));
    const eligible = stable
      .filter(({ publishedAt }) => Date.parse(publishedAt) <= cutoff)
      .map(({ tag }) => tag);
    if (eligible.length === 0) {
      return needsPerson(repo, 'No stable release is old enough.');
    }
    const tags = uses.map(({ tag }) => tag);
    const newestCurrent = newestVersion(tags);
    const adopted = uses.find(({ tag }) => compareVersions(tag, newestCurrent) === 0);
    const adoptedSha = await lookup.commitSha(repo, adopted.tag);
    const rewritten =
      FULL_SHA.test(adoptedSha ?? '') &&
      uses.some(({ tag, sha }) => tag === adopted.tag && sha !== adoptedSha);
    const observed = {};
    const trusted = new Map();
    const moved = [];
    const missing = [];
    for (const { tag } of stable.filter(({ tag }) => compareVersions(tag, newestCurrent) >= 0)) {
      if (tag === adopted.tag) {
        if (eligible.includes(tag)) {
          trusted.set(tag, adopted.sha);
        }
        continue;
      }
      const sha = await lookup.commitSha(repo, tag);
      if (!FULL_SHA.test(sha ?? '')) {
        missing.push(tag);
        continue;
      }
      const key = `${repo}@${tag}`;
      observed[key] = ledger[key] ?? { sha, firstSeen: now };
      if (observed[key].sha !== sha) {
        moved.push(tag);
      } else if (eligible.includes(tag) && observed[key].firstSeen <= cutoff) {
        trusted.set(tag, sha);
      }
    }
    const warnings = [
      ...(rewritten
        ? [
            {
              ecosystem: 'actions',
              name: repo,
              reason: `The tag ${adopted.tag} now points to another commit than the pin in a workflow file. Read the release before you trust it.`,
            },
          ]
        : []),
      ...moved.map((tag) => ({
        ecosystem: 'actions',
        name: repo,
        reason: `The tag ${tag} points to a new commit since the job first saw it. Read the release before you trust it.`,
      })),
      ...missing
        .filter((tag) => eligible.includes(tag))
        .map((tag) => ({
          ecosystem: 'actions',
          name: repo,
          reason: `The lookup found no commit for ${tag}.`,
        })),
    ];
    if (trusted.size === 0) {
      return { observed, needsPerson: warnings };
    }
    const to = newestVersion([...trusted.keys()]);
    if (tags.every((tag) => compareVersions(tag, to) === 0)) {
      return { observed, needsPerson: warnings };
    }
    return {
      observed,
      needsPerson: warnings,
      candidate: {
        ecosystem: 'actions',
        name: repo,
        from: oldestVersion(tags),
        to,
        direct: true,
        data: {
          toSha: trusted.get(to),
          major: /\d+/.exec(to)[0] !== /\d+/.exec(newestCurrent)[0],
        },
      },
    };
  } catch (error) {
    return needsPerson(
      repo,
      `The lookup failed. ${error instanceof Error ? error.message : String(error)}`,
    );
  }
}

export async function planActions({ files, lookup, now, cooldownDays, ledger }) {
  const cutoff = now - cooldownDays * DAY_MS;
  const byRepo = Map.groupBy(
    Object.values(files).flatMap((text) => parseActionUses(text)),
    ({ repo }) => repo,
  );
  const results = await Promise.all(
    [...byRepo].map(([repo, uses]) => planRepo({ repo, uses, lookup, cutoff, ledger, now })),
  );
  return {
    candidates: results.flatMap(({ candidate }) => candidate ?? []),
    needsPerson: results.flatMap((result) => result.needsPerson ?? []),
    ledger: Object.fromEntries(
      [...byRepo.keys()].flatMap((repo, index) =>
        results[index].observed
          ? Object.entries(results[index].observed)
          : Object.entries(ledger).filter(([key]) => key.startsWith(`${repo}@`)),
      ),
    ),
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
  const tagReleases = async (repo) => {
    const names = ((await get(`${repo}/tags?per_page=30`)) ?? [])
      .map(({ name }) => name)
      .filter(isStable)
      .sort((a, b) => compareVersions(b, a))
      .slice(0, MAX_TAG_FALLBACK);
    return Promise.all(
      names.map(async (tag) => ({
        tag,
        publishedAt: (await get(`${repo}/commits/${tag}`))?.commit?.committer?.date,
      })),
    );
  };
  return {
    async releases(repo) {
      const body = await get(`${repo}/releases?per_page=30`);
      if (body?.length === 0) {
        return tagReleases(repo);
      }
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
