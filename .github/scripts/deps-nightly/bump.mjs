const MAX_LISTED = 100;

export function pnpmCommands(entry, releaseAge) {
  const names = (direct) =>
    entry.members.filter((member) => member.direct === direct).map(({ name }) => name);
  const update = (flags, direct) =>
    names(direct).length > 0
      ? [
          [
            'pnpm',
            'update',
            '-r',
            ...flags,
            '--lockfile-only',
            '--loglevel',
            'error',
            releaseAge,
            ...names(direct),
          ],
        ]
      : [];
  return [...update(['--latest'], true), ...update([], false)];
}

export function uvLockArgs(members, cooldownFlag) {
  return [
    'lock',
    ...cooldownFlag,
    ...members.flatMap(({ name, to }) => ['--upgrade-package', `${name}==${to}`]),
  ];
}

export function renderTitle(entry, scope) {
  const subject = entry.isGroup
    ? `bump ${entry.name} packages`
    : `bump ${entry.name} from ${entry.members[0].from} to ${entry.members[0].to}`;
  return `build(${scope}): ${subject}`;
}

function listed(lines) {
  const shown = lines.slice(0, MAX_LISTED).map((line) => `- ${line}`);
  return lines.length > MAX_LISTED ? [...shown, `- and ${lines.length - MAX_LISTED} more`] : shown;
}

export function renderBody({ entry, changes, projects, cooldownDays }) {
  const intro = entry.isGroup
    ? `This pull request bumps the \`${entry.name}\` group. It holds ${entry.members.length} packages that move together.`
    : `This pull request bumps \`${entry.name}\` from ${entry.members[0].from} to ${entry.members[0].to}.`;
  const changeLines = [
    ...new Set(
      changes.map(
        ({ name, from, to }) =>
          `\`${name}\`: ${from.join(', ') || 'new'} -> ${to.join(', ') || 'removed'}`,
      ),
    ),
  ];
  return [
    intro,
    '',
    `The nightly dependency job made this change. It only uses versions that are at least ${cooldownDays} days old.`,
    '',
    `### Packages that changed in the lock files (${changeLines.length})`,
    '',
    ...listed(changeLines),
    '',
    '### Projects that moved',
    '',
    ...(projects.length > 0
      ? listed(projects.map((project) => `\`${project}\``))
      : ['- None. Only the lock file changed.']),
    '',
  ].join('\n');
}
