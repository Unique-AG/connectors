import assert from 'node:assert';
import { dirname } from 'node:path/posix';
import { compareVersions, isStable } from './versions.mjs';

const DAY_MS = 24 * 60 * 60 * 1000;
const TIMEOUT_MS = 20_000;
const CORE_REPO = 'hashicorp/terraform';
const PART = /^(~>|>=|<=|!=|>|<|=)?\s*(\d+(?:\.\d+)*)$/;

function blockBody(text, start) {
  let depth = 1;
  let index = start;
  while (depth > 0 && index < text.length) {
    const char = text[index++];
    depth += char === '{' ? 1 : char === '}' ? -1 : 0;
  }
  return text.slice(start, index - 1);
}

export function parseProviders(text) {
  const code = text.replace(/^\s*(?:#|\/\/).*$/gm, '');
  const requiredVersion = /required_version\s*=\s*"([^"]+)"/.exec(code)?.[1];
  const opening = /required_providers\s*\{/.exec(code);
  const body = opening ? blockBody(code, opening.index + opening[0].length) : '';
  const providers = [...body.matchAll(/([\w-]+)\s*=\s*\{([^{}]*)\}/g)].flatMap((entry) => {
    const source = /source\s*=\s*"([^"]+)"/.exec(entry[2])?.[1];
    const constraint = /version\s*=\s*"([^"]+)"/.exec(entry[2])?.[1];
    return source && constraint ? [{ name: entry[1], source, constraint }] : [];
  });
  return { requiredVersion, providers };
}

function upperBound(release) {
  const kept = release.length === 1 ? release : release.slice(0, -1);
  return [...kept.slice(0, -1), kept.at(-1) + 1].join('.');
}

function satisfiesPart(version, part) {
  const match = PART.exec(part.trim());
  assert.ok(match, `Not a version constraint: ${part}`);
  const [, operator = '=', limit] = match;
  const order = compareVersions(version, limit);
  switch (operator) {
    case '~>':
      return order >= 0 && compareVersions(version, upperBound(limit.split('.').map(Number))) < 0;
    case '>=':
      return order >= 0;
    case '>':
      return order > 0;
    case '<=':
      return order <= 0;
    case '<':
      return order < 0;
    case '!=':
      return order !== 0;
    default:
      return order === 0;
  }
}

export function satisfies(version, constraint) {
  return constraint.split(',').every((part) => satisfiesPart(version, part));
}

function usagesByRepo(files) {
  const usages = new Map();
  const add = (repo, name, constraint, folder) =>
    usages.set(repo, [...(usages.get(repo) ?? []), { name, constraint, folder }]);
  for (const [path, text] of Object.entries(files)) {
    const { requiredVersion, providers } = parseProviders(text);
    const folder = dirname(path);
    if (requiredVersion) {
      add(CORE_REPO, 'terraform', requiredVersion, folder);
    }
    for (const { name, source, constraint } of providers) {
      const [namespace] = source.split('/').slice(-2);
      add(`${namespace}/terraform-provider-${name}`, name, constraint, folder);
    }
  }
  return usages;
}

function describeViolations(name, version, violations) {
  const byConstraint = Map.groupBy(violations, ({ constraint }) => constraint);
  const sentences = [...byConstraint].map(
    ([constraint, group]) =>
      `It is outside "${constraint}" in ${[...new Set(group.map(({ folder }) => folder))].join(', ')}.`,
  );
  return [`The newest release of ${name} is ${version}.`, ...sentences].join(' ');
}

async function checkRepo(repo, usages, lookup, cutoff) {
  const name = usages[0].name;
  try {
    const eligible = (await lookup.releases(repo)).filter(
      ({ tag, publishedAt }) => isStable(tag) && Date.parse(publishedAt) <= cutoff,
    );
    if (eligible.length === 0) {
      return [];
    }
    const newest = eligible.reduce((best, release) =>
      compareVersions(release.tag, best.tag) > 0 ? release : best,
    ).tag;
    const violations = usages.filter(({ constraint }) => !satisfies(newest, constraint));
    return violations.length > 0
      ? [{ ecosystem: 'terraform', name, reason: describeViolations(name, newest, violations) }]
      : [];
  } catch {
    return [{ ecosystem: 'terraform', name, reason: 'The release lookup failed.' }];
  }
}

export async function planTerraform({ files, lookup, now, cooldownDays }) {
  const cutoff = now - cooldownDays * DAY_MS;
  const checks = await Promise.all(
    [...usagesByRepo(files)].map(([repo, usages]) => checkRepo(repo, usages, lookup, cutoff)),
  );
  return { needsPerson: checks.flat() };
}

export function createTerraformLookup(token, fetchImpl = fetch) {
  const headers = {
    Accept: 'application/vnd.github+json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  return {
    async releases(repo) {
      const response = await fetchImpl(
        `https://api.github.com/repos/${repo}/releases?per_page=30`,
        { headers, signal: AbortSignal.timeout(TIMEOUT_MS) },
      );
      if (response.status !== 200) {
        throw new Error(`GitHub answered ${response.status} for ${repo}.`);
      }
      return (await response.json())
        .filter((release) => !release.draft && !release.prerelease)
        .map((release) => ({
          tag: release.tag_name.replace(/^v/, ''),
          publishedAt: release.published_at,
        }));
    },
  };
}
