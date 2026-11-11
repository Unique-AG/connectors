import assert from 'node:assert';
import { markerOf } from './state.mjs';
import { formatChange, pairVersions, versionLine } from './versions.mjs';

const MAX_LISTED = 100;

export function pnpmCommands(entry, releaseAge) {
  const names = entry.members.filter(({ direct }) => direct).map(({ name }) => name);
  return names.length > 0
    ? [
        [
          'pnpm',
          'update',
          '-r',
          '--latest',
          '--lockfile-only',
          '--loglevel',
          'error',
          releaseAge,
          ...names,
        ],
      ]
    : [];
}

export const pnpmInstallArgs = (releaseAge) => [
  'install',
  '--lockfile-only',
  '--ignore-scripts',
  '--loglevel',
  'error',
  releaseAge,
];

export function withOverrides(packageJson, members, locked) {
  const parsed = JSON.parse(packageJson);
  const pins = Object.fromEntries(
    members.flatMap(({ name, from, to }) =>
      to.split(', ').map((target) => {
        if (locked.get(name)?.length === 1) {
          return [name, target];
        }
        const old = from
          .split(', ')
          .find((version) => versionLine(version) === versionLine(target));
        assert.ok(old, `${name} ${target} has no old version on the same line`);
        return [`${name}@${versionLine(old)}`, target];
      }),
    ),
  );
  parsed.pnpm = { ...parsed.pnpm, overrides: { ...parsed.pnpm?.overrides, ...pins } };
  return `${JSON.stringify(parsed, null, 2)}\n`;
}

export function uvLockArgs(members, cooldownFlag) {
  return [
    'lock',
    ...cooldownFlag,
    ...members.flatMap(({ name, to }) => ['--upgrade-package', `${name}==${to}`]),
  ];
}

const fromTo = ({ from, to }) =>
  pairVersions(from, to)
    .map(([old, target]) => `from ${old} to ${target}`)
    .join(' and ');

export function renderTitle(entry, scope) {
  const subject = entry.isGroup
    ? `bump ${entry.name} packages`
    : `bump ${entry.name} ${fromTo(entry.members[0])}`;
  return `build(${scope}): ${subject}`;
}

function listed(lines) {
  const shown = lines.slice(0, MAX_LISTED).map((line) => `- ${line}`);
  return lines.length > MAX_LISTED ? [...shown, `- and ${lines.length - MAX_LISTED} more`] : shown;
}

export function renderBody({ entry, changes, projects, cooldownDays }) {
  const intro = entry.isGroup
    ? `Bump the \`${entry.name}\` group. It holds ${entry.members.length} packages that move together.`
    : entry.ecosystem === 'terraform'
      ? `Change the version constraint of the provider \`${entry.name}\` from \`${entry.members[0].from}\`, so that the release \`${entry.members[0].to}\` fits.`
      : `Bump \`${entry.name}\` ${fromTo(entry.members[0])}.`;
  const changeLines = [
    ...new Set(
      changes.map(
        ({ name, from, to }) =>
          `\`${name}\`: ${from.length && to.length ? formatChange(from, to) : `${from.join(', ') || 'new'} -> ${to.join(', ') || 'removed'}`}`,
      ),
    ),
  ];
  const major = entry.members.some(({ data }) => data?.major);
  const locked = entry.ecosystem === 'npm' || entry.ecosystem === 'uv';
  return [
    intro,
    '',
    `${locked ? 'Packages that changed in the lock files' : 'Versions that changed'} (${changeLines.length}):`,
    '',
    ...listed(changeLines),
    '',
    '---',
    '',
    `The nightly dependency job made this change. It only uses versions that are at least ${cooldownDays} days old.`,
    '',
    ...(major
      ? ['This is a major bump. A person must read the release notes before the merge.', '']
      : []),
    `### ${locked ? 'Projects that moved' : 'Files that changed'}`,
    '',
    ...(projects.length > 0
      ? listed(projects.map((project) => `\`${project}\``))
      : [`- None. ${locked ? 'Only the lock file changed.' : 'No file changed.'}`]),
    '',
    markerOf(entry.key),
    '',
  ].join('\n');
}
