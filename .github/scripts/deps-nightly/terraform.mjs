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

const PART_TEXT = /^(\s*(?:~>|>=|<=|!=|>|<|=)?\s*)(\d+(?:\.\d+)*)(\s*)$/;

function retargetPart(part, version) {
  if (satisfiesPart(version, part)) {
    return part;
  }
  const [, prefix, limit, suffix] = PART_TEXT.exec(part);
  const operator = /^\s*(~>|<=|<|=)?/.exec(prefix)[1] ?? '=';
  const count = limit.split('.').length;
  const release = version.split('.').map(Number);
  const leading = Array.from({ length: count }, (_, index) => release[index] ?? 0);
  switch (operator) {
    case '~>':
      return `${prefix}${leading.join('.')}${suffix}`;
    case '<':
      return `${prefix}${[...leading.slice(0, -1), leading.at(-1) + 1].join('.')}${suffix}`;
    default:
      return `${prefix}${version}${suffix}`;
  }
}

export function retargetConstraint(constraint, version) {
  const result = constraint
    .split(',')
    .map((part) => retargetPart(part, version))
    .join(',');
  assert.ok(satisfies(version, result), `Cannot fit ${version} into "${constraint}".`);
  return result;
}

function applyToText(text, name, version) {
  const opening = /required_providers\s*\{/.exec(text);
  if (!opening) {
    return text;
  }
  const start = opening.index + opening[0].length;
  const body = blockBody(text, start);
  const entry = new RegExp(`(\\b${name}\\s*=\\s*\\{[^{}]*?version\\s*=\\s*")([^"]+)(")`).exec(body);
  if (!entry) {
    return text;
  }
  const updated =
    body.slice(0, entry.index) +
    entry[1] +
    retargetConstraint(entry[2], version) +
    entry[3] +
    body.slice(entry.index + entry[0].length);
  return text.slice(0, start) + updated + text.slice(start + body.length);
}

export function applyTerraform(files, { name, to }) {
  return Object.fromEntries(
    Object.entries(files)
      .map(([path, text]) => [path, applyToText(text, name, to)])
      .filter(([path, text]) => text !== files[path]),
  );
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
      const [namespace, type] = source.split('/').slice(-2);
      add(`${namespace}/terraform-provider-${type}`, name, constraint, folder);
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
      return {};
    }
    const newest = eligible.reduce((best, release) =>
      compareVersions(release.tag, best.tag) > 0 ? release : best,
    ).tag;
    const violations = usages.filter(({ constraint }) => !satisfies(newest, constraint));
    if (violations.length === 0) {
      return {};
    }
    if (repo === CORE_REPO) {
      return {
        needsPerson: {
          ecosystem: 'terraform',
          name,
          reason: describeViolations(name, newest, violations),
        },
      };
    }
    violations.forEach(({ constraint }) => retargetConstraint(constraint, newest));
    return {
      candidate: {
        ecosystem: 'terraform',
        name,
        from: [...new Set(violations.map(({ constraint }) => constraint))].join(' and '),
        to: newest,
        direct: true,
        data: { major: true },
      },
    };
  } catch {
    return { needsPerson: { ecosystem: 'terraform', name, reason: 'The release lookup failed.' } };
  }
}

export async function planTerraform({ files, lookup, now, cooldownDays }) {
  const cutoff = now - cooldownDays * DAY_MS;
  const checks = await Promise.all(
    [...usagesByRepo(files)].map(([repo, usages]) => checkRepo(repo, usages, lookup, cutoff)),
  );
  return {
    candidates: checks.flatMap(({ candidate }) => candidate ?? []),
    needsPerson: checks.flatMap(({ needsPerson }) => needsPerson ?? []),
  };
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
