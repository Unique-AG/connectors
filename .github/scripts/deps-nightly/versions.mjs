import assert from 'node:assert';

const VERSION = /^v?(\d+(?:\.\d+)*)(.*)$/;
const POST = /^\.?post(\d+)$/;

function parse(version) {
  const match = VERSION.exec(version);
  assert.ok(match, `Not a version: ${version}`);
  return { release: match[1].split('.').map(Number), tail: match[2] };
}

function tailRank(tail) {
  if (tail === '') {
    return 0;
  }
  const post = POST.exec(tail);
  return post ? 1 + Number(post[1]) : -1;
}

export function isStable(version) {
  const match = VERSION.exec(version);
  return match !== null && tailRank(match[2]) >= 0;
}

export function compareVersions(a, b) {
  const left = parse(a);
  const right = parse(b);
  const length = Math.max(left.release.length, right.release.length);
  for (let index = 0; index < length; index++) {
    const difference = (left.release[index] ?? 0) - (right.release[index] ?? 0);
    if (difference !== 0) {
      return Math.sign(difference);
    }
  }
  const rankDifference = tailRank(left.tail) - tailRank(right.tail);
  if (rankDifference !== 0) {
    return Math.sign(rankDifference);
  }
  if (tailRank(left.tail) < 0) {
    return Math.sign(left.tail.localeCompare(right.tail, 'en', { numeric: true }));
  }
  return 0;
}

export function newestVersion(versions) {
  return versions.reduce((newest, version) =>
    compareVersions(version, newest) > 0 ? version : newest,
  );
}

export function oldestVersion(versions) {
  return versions.reduce((oldest, version) =>
    compareVersions(version, oldest) < 0 ? version : oldest,
  );
}

export function isMajorBump(from, to) {
  const majors = (versions) => [versions].flat().map((version) => Number(/\d+/.exec(version)?.[0]));
  const known = new Set(majors(from));
  return majors(to).some((major) => !known.has(major) && major > Math.min(...known));
}

export function versionLine(version) {
  const [major, minor, patch] = version.split('.').map((part) => Number.parseInt(part, 10));
  if (major > 0) {
    return `>=${major}.0.0 <${major + 1}.0.0`;
  }
  return minor > 0 ? `>=0.${minor}.0 <0.${minor + 1}.0` : `>=0.0.${patch} <0.0.${patch + 1}`;
}

const versionList = (value) => [value].flat().flatMap((item) => item.split(', '));

function oldVersions(from) {
  const parts = versionList(from);
  return parts.every((part) => VERSION.test(part)) ? parts : [[from].flat().join(', ')];
}

export function pairVersions(from, to) {
  const olds = oldVersions(from);
  if (olds.length === 1) {
    return versionList(to).map((target) => [olds[0], target]);
  }
  return versionList(to).map((target) => {
    const below = olds.filter((old) => compareVersions(old, target) <= 0);
    return [
      olds.find((old) => versionLine(old) === versionLine(target)) ??
        (below.length > 0 ? newestVersion(below) : olds[0]),
      target,
    ];
  });
}

export function formatChange(from, to) {
  return pairVersions(from, to)
    .map(([old, target]) => `${old} -> ${target}`)
    .join(', ');
}

export function updateType(from, to) {
  const [before, after] = [from, to].map((version) =>
    /\d+(?:\.\d+)*/.exec(version)?.[0].split('.').map(Number),
  );
  if (!(before && after)) {
    return 'unknown';
  }
  if (after[0] !== before[0]) {
    return 'major';
  }
  return (after[1] ?? 0) === (before[1] ?? 0) ? 'patch' : 'minor';
}
