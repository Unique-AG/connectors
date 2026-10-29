import { dirname } from 'node:path';
import { renderBody, renderTitle } from './bump.mjs';
import {
  changedPackages,
  movedPnpmImporters,
  parsePnpmPackages,
  parseUvPackages,
} from './locks.mjs';
import { readFiles, trackedFiles } from './repo.mjs';
import { runOrThrow } from './run.mjs';
import { commitScope } from './scope.mjs';

export function lockFiles(ecosystem) {
  if (ecosystem === 'npm') {
    return readFiles(['pnpm-lock.yaml']);
  }
  return ecosystem === 'uv' ? readFiles(trackedFiles(/(^|\/)uv\.lock$/)) : {};
}

export function changedFiles() {
  return runOrThrow('git', ['status', '--porcelain', '--untracked-files=all'])
    .split('\n')
    .filter(Boolean)
    .map((line) => line.slice(3));
}

function lockChanges({ ecosystem, before, after }) {
  if (ecosystem === 'npm') {
    const [from, to] = [before['pnpm-lock.yaml'], after['pnpm-lock.yaml']];
    return {
      changes: changedPackages(parsePnpmPackages(from), parsePnpmPackages(to)),
      projects: movedPnpmImporters(from, to),
    };
  }
  const moved = Object.keys(after).filter((path) => before[path] !== after[path]);
  return {
    changes: moved.flatMap((path) =>
      changedPackages(parseUvPackages(before[path]), parseUvPackages(after[path])),
    ),
    projects: moved.map((path) => dirname(path)),
  };
}

export function renderPr({ entry, files, before, after, gitcommitizen, cooldownDays }) {
  const { changes, projects } =
    entry.ecosystem === 'npm' || entry.ecosystem === 'uv'
      ? lockChanges({ ecosystem: entry.ecosystem, before, after })
      : {
          changes: entry.members.map(({ name, from, to }) => ({ name, from: [from], to: [to] })),
          projects: files,
        };
  return {
    title: renderTitle(entry, commitScope(files, gitcommitizen)),
    body: renderBody({ entry, changes, projects, cooldownDays }),
  };
}
