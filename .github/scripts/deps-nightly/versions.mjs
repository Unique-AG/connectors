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
  return Math.max(...majors(to)) > Math.min(...majors(from));
}
