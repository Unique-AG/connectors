import { compareVersions, newestVersion } from './versions.mjs';

const PNPM_PACKAGE_KEY = /^ {2}'?((?:@[^/@']+\/)?[^@'/]+)@(\d[^'(]*)'?:$/;
const UV_PACKAGE = /\[\[package\]\]\nname = "([^"]+)"\nversion = "([^"]+)"\nsource = \{ registry/g;
const REQUIREMENT = /"([A-Za-z0-9][\w.-]*)(\[[^\]]*\])?([<>=!~][^";]*)(?:;[^"]*)?"/g;

export function normalizeName(name) {
  return name.toLowerCase().replace(/[-_.]+/g, '-');
}

function addVersion(packages, name, version) {
  const versions = packages.get(name) ?? [];
  return new Map(packages).set(
    name,
    versions.includes(version) ? versions : [...versions, version],
  );
}

export function parsePnpmPackages(lock) {
  const section = lock.split('\npackages:\n')[1]?.split(/\n\S/)[0] ?? '';
  return section.split('\n').reduce((packages, line) => {
    const match = PNPM_PACKAGE_KEY.exec(line);
    return match ? addVersion(packages, match[1], match[2]) : packages;
  }, new Map());
}

export function parseUvPackages(lock) {
  return [...lock.matchAll(UV_PACKAGE)].reduce(
    (packages, match) => addVersion(packages, normalizeName(match[1]), match[2]),
    new Map(),
  );
}

export function changedPackages(before, after) {
  const names = new Set([...before.keys(), ...after.keys()]);
  return [...names].sort().flatMap((name) => {
    const oldVersions = before.get(name) ?? [];
    const newVersions = after.get(name) ?? [];
    const from = oldVersions.filter((version) => !newVersions.includes(version));
    const to = newVersions.filter((version) => !oldVersions.includes(version));
    return from.length || to.length
      ? [{ name, from: from.sort(compareVersions), to: to.sort(compareVersions) }]
      : [];
  });
}

export function findDowngrades(before, after) {
  return [...before].flatMap(([name, oldVersions]) => {
    const newVersions = after.get(name);
    return newVersions &&
      compareVersions(newestVersion(newVersions), newestVersion(oldVersions)) < 0
      ? [name]
      : [];
  });
}

export function movedPnpmImporters(before, after) {
  const blocks = (lock) => {
    const section = lock.split('\nimporters:\n')[1]?.split(/\n\S/)[0] ?? '';
    return new Map(
      section
        .split(/^ {2}(?=\S)/m)
        .filter(Boolean)
        .map((block) => [block.split('\n')[0].replace(/:$/, ''), block]),
    );
  };
  const oldBlocks = blocks(before);
  return [...blocks(after)]
    .filter(([path, block]) => oldBlocks.get(path) !== block)
    .map(([path]) => path);
}

export function parseRequirements(pyproject) {
  return [...pyproject.matchAll(REQUIREMENT)].map((match) => ({
    name: normalizeName(match[1]),
    spec: match[3].trim(),
  }));
}

export function pinnedVersion(spec) {
  return /^==([^,\s]+)$/.exec(spec)?.[1];
}

export function pinEdit(pyproject, name, to) {
  return pyproject.replace(REQUIREMENT, (text, candidate, _extras, spec) =>
    normalizeName(candidate) === name && pinnedVersion(spec.trim())
      ? text.replace(spec.trim(), `==${to}`)
      : text,
  );
}

export function restoreUvLockHeader(after, before) {
  const revision = /^revision = \d+$/m.exec(before)?.[0];
  const withoutCooldown = after
    .replace(/^exclude-newer(?:-span)? = .*\n/gm, '')
    .replace(/\[options\]\n\n/, '');
  return revision ? withoutCooldown.replace(/^revision = \d+$/m, revision) : withoutCooldown;
}

export function parseUvDryRun(output) {
  const [, ...blocks] = output.split(/^== (\S+): .*$/m);
  const updates = new Map();
  for (let index = 0; index < blocks.length; index += 2) {
    updates.set(
      blocks[index],
      [...blocks[index + 1].matchAll(/^Update (\S+) v(\S+) -> v(\S+)$/gm)].map((match) => ({
        name: match[1],
        from: match[2],
        to: match[3],
      })),
    );
  }
  return updates;
}

export function hasUvCooldown(pyprojects) {
  return pyprojects.some((pyproject) => /^exclude-newer\b/m.test(pyproject));
}
