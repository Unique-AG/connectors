import { normalizeName, parseRequirements, parseUvPackages, pinnedVersion } from './locks.mjs';
import { compareVersions, isStable, newestVersion, oldestVersion } from './versions.mjs';

const DAY_MS = 24 * 60 * 60 * 1000;

function matchesPattern(pattern, name) {
  return new RegExp(`^${pattern.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*')}$`).test(
    name,
  );
}

function violatesCap(version, spec) {
  return spec.split(',').some((part) => {
    const limit = /^<(=?)(\d[^\s,]*)$/.exec(part.trim());
    return limit !== null && compareVersions(version, limit[2]) >= (limit[1] ? 1 : 0);
  });
}

function overrideNames(overrides) {
  return new Set(Object.keys(overrides).map((key) => /^(@?[^@]+)/.exec(key)[1]));
}

export function npmCandidates({ outdated, lockChanges, overrides }) {
  const pinned = overrideNames(overrides);
  const direct = Object.entries(outdated).flatMap(([name, { wanted, latest }]) => {
    const order = compareVersions(latest, wanted);
    if (order === 0) {
      return [];
    }
    const found = { ecosystem: 'npm', name, from: wanted, to: latest, direct: true };
    if (order < 0) {
      return [{ ...found, reason: `The newest version ${latest} is older than ${wanted}.` }];
    }
    return [found];
  });
  const transitive = lockChanges
    .filter(({ name, from, to }) => from.length > 0 && to.length > 0 && !(name in outdated))
    .map(({ name, from, to }) => ({
      ecosystem: 'npm',
      name,
      from: from.join(', '),
      to: to.join(', '),
      direct: false,
    }));
  const all = [...direct, ...transitive];
  return {
    candidates: all.filter(({ name, reason }) => !reason && !pinned.has(name)),
    needsPerson: all.flatMap(({ ecosystem, name, reason }) => {
      if (reason) {
        return [{ ecosystem, name, reason }];
      }
      return pinned.has(name)
        ? [{ ecosystem, name, reason: 'The pnpm overrides pin this package.' }]
        : [];
    }),
  };
}

function eligibleLatest(pypi, now, cooldownDays) {
  const cutoff = now - cooldownDays * DAY_MS;
  const versions = Object.entries(pypi.releases ?? {})
    .filter(
      ([version, files]) =>
        isStable(version) &&
        files.length > 0 &&
        files.every((file) => !file.yanked && Date.parse(file.upload_time_iso_8601) <= cutoff),
    )
    .map(([version]) => version);
  return versions.length > 0 ? newestVersion(versions) : undefined;
}

export async function latestEligibleVersions(names, fetchPypi, now, cooldownDays) {
  const pairs = await Promise.all(
    names.map(async (name) => [
      name,
      eligibleLatest((await fetchPypi(name)) ?? {}, now, cooldownDays),
    ]),
  );
  return new Map(pairs.filter(([, version]) => version !== undefined));
}

export function uvCandidates({ projects, latest }) {
  const holders = new Map();
  const targets = new Map();
  const needsPerson = [];
  const addTarget = (name, to) => targets.set(name, [...(targets.get(name) ?? []), to]);

  const requirements = projects.flatMap(({ project, pyproject }) =>
    parseRequirements(pyproject).map((requirement) => ({ ...requirement, project })),
  );
  for (const { project, lock, updates } of projects) {
    for (const [name, versions] of parseUvPackages(lock)) {
      holders.set(name, [
        ...(holders.get(name) ?? []),
        { project, current: newestVersion(versions) },
      ]);
    }
    for (const { name, to } of updates) {
      addTarget(normalizeName(name), to);
    }
  }
  const pinnedNames = new Set(
    requirements.filter(({ spec }) => pinnedVersion(spec)).map(({ name }) => name),
  );
  for (const name of pinnedNames) {
    const newest = latest.get(name);
    const cap = requirements.find(
      (requirement) => requirement.name === name && violatesCap(newest ?? '0', requirement.spec),
    );
    const pins = requirements.filter(
      ({ name: other, spec }) => other === name && pinnedVersion(spec),
    );
    if (newest && pins.some(({ spec }) => compareVersions(newest, pinnedVersion(spec)) > 0)) {
      if (cap) {
        needsPerson.push({
          ecosystem: 'uv',
          name,
          reason: `Version ${newest} breaks the limit ${cap.spec} in ${cap.project}.`,
        });
      } else {
        addTarget(name, newest);
      }
    }
  }

  const candidates = [];
  for (const [name, versions] of targets) {
    const target = oldestVersion(versions);
    const current = holders.get(name) ?? [];
    const ahead = current.find((holder) => compareVersions(holder.current, target) > 0);
    if (ahead) {
      needsPerson.push({
        ecosystem: 'uv',
        name,
        reason: `The target ${target} is older than ${ahead.current} in ${ahead.project}.`,
      });
      continue;
    }
    const behind = current.filter((holder) => compareVersions(holder.current, target) < 0);
    if (behind.length > 0) {
      candidates.push({
        ecosystem: 'uv',
        name,
        from: oldestVersion(behind.map((holder) => holder.current)),
        to: target,
        direct: pinnedNames.has(name),
      });
    }
  }
  return { candidates, needsPerson };
}

function slugOf(ecosystem, name) {
  return `${ecosystem}-${name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')}`;
}

function interleave(entries) {
  const lanes = Object.values(Object.groupBy(entries, ({ ecosystem }) => ecosystem));
  const longest = Math.max(0, ...lanes.map((lane) => lane.length));
  return Array.from({ length: longest }, (_, index) => lanes.map((lane) => lane[index]))
    .flat()
    .filter(Boolean);
}

export function buildPlan({ candidates, needsPerson, config, openBranches }) {
  const buckets = Map.groupBy(candidates, (candidate) => {
    const group = config.groups.find(
      ({ ecosystem, patterns }) =>
        ecosystem === candidate.ecosystem &&
        patterns.some((pattern) => matchesPattern(pattern, candidate.name)),
    );
    return JSON.stringify(
      group
        ? [candidate.ecosystem, 'group', group.name]
        : [candidate.ecosystem, 'package', candidate.name],
    );
  });
  const entries = [...buckets].map(([key, members]) => {
    const [, kind, groupName] = JSON.parse(key);
    const isGroup = kind === 'group' && members.length > 1;
    const name = isGroup ? groupName : members[0].name;
    return {
      ecosystem: members[0].ecosystem,
      slug: slugOf(members[0].ecosystem, name),
      name,
      isGroup,
      members: members.map(({ name: memberName, from, to, direct, data }) => ({
        name: memberName,
        from,
        to,
        direct,
        ...(data ? { data } : {}),
      })),
    };
  });
  const ordered = entries.sort(
    (a, b) =>
      Number(b.members.some(({ direct }) => direct)) -
        Number(a.members.some(({ direct }) => direct)) || a.slug.localeCompare(b.slug),
  );
  const open = new Set(openBranches);
  const skipped = ordered.filter(({ slug }) => open.has(`deps/${slug}`));
  const fresh = interleave(ordered.filter(({ slug }) => !open.has(`deps/${slug}`)));
  return {
    entries: fresh.slice(0, config.maxNewPullRequests),
    skipped,
    deferred: fresh.slice(config.maxNewPullRequests),
    needsPerson,
  };
}

function describe({ name, isGroup, members }) {
  if (isGroup) {
    return `${name}: ${members.length} packages`;
  }
  return `${name}: ${members[0].from} -> ${members[0].to}`;
}

export function renderSummary({ entries, skipped, deferred, needsPerson }, modeNote) {
  const section = (title, items) =>
    items.length > 0
      ? [`### ${title} (${items.length})`, '', ...items.map((item) => `- ${item}`), '']
      : [];
  return [
    '## Dependency plan',
    '',
    modeNote,
    '',
    ...section(
      'Pull requests for this run',
      entries.map((entry) => `${entry.ecosystem} ${describe(entry)}`),
    ),
    ...section(
      'Skipped because a pull request is open',
      skipped.map((entry) => `${entry.ecosystem} ${entry.name}`),
    ),
    ...section(
      'Left for a later run',
      deferred.map((entry) => `${entry.ecosystem} ${describe(entry)}`),
    ),
    ...section(
      'Needs a person',
      needsPerson.map(({ ecosystem, name, reason }) => `${ecosystem} ${name}: ${reason}`),
    ),
  ].join('\n');
}
