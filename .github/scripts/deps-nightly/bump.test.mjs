import assert from 'node:assert';
import { describe, it } from 'node:test';
import { pnpmCommands, renderBody, renderTitle, uvLockArgs } from './bump.mjs';

const RELEASE_AGE = '--config.minimumReleaseAge=4320';
const single = {
  ecosystem: 'npm',
  name: 'zod',
  isGroup: false,
  members: [{ name: 'zod', from: '4.6.5', to: '4.6.7', direct: true }],
};
const group = {
  ecosystem: 'npm',
  name: 'rollup',
  isGroup: true,
  members: [
    { name: 'rollup', from: '4.0.0', to: '4.1.0', direct: true },
    { name: '@rollup/rollup-linux-x64-gnu', from: '4.0.0', to: '4.1.0', direct: false },
  ],
};

describe('pnpmCommands', () => {
  it('updates a direct package with --latest', () => {
    assert.deepStrictEqual(pnpmCommands(single, RELEASE_AGE), [
      [
        'pnpm',
        'update',
        '-r',
        '--latest',
        '--lockfile-only',
        '--loglevel',
        'error',
        RELEASE_AGE,
        'zod',
      ],
    ]);
  });

  it('runs one command for the direct members and one for the indirect members', () => {
    const commands = pnpmCommands(group, RELEASE_AGE);
    assert.deepStrictEqual(
      commands.map((command) => [command.includes('--latest'), command.at(-1)]),
      [
        [true, 'rollup'],
        [false, '@rollup/rollup-linux-x64-gnu'],
      ],
    );
  });
});

describe('uvLockArgs', () => {
  it('pins every member to its target version', () => {
    const members = [
      { name: 'httpx2', to: '2.16.0' },
      { name: 'httpcore2', to: '2.16.0' },
    ];
    assert.deepStrictEqual(uvLockArgs(members, ['--exclude-newer', '3 days']), [
      'lock',
      '--exclude-newer',
      '3 days',
      '--upgrade-package',
      'httpx2==2.16.0',
      '--upgrade-package',
      'httpcore2==2.16.0',
    ]);
  });

  it('adds no cooldown flag when the repository sets one', () => {
    assert.deepStrictEqual(uvLockArgs([{ name: 'a', to: '1' }], []), [
      'lock',
      '--upgrade-package',
      'a==1',
    ]);
  });
});

describe('renderTitle', () => {
  it('names the package and both versions', () => {
    assert.strictEqual(renderTitle(single, 'deps'), 'build(deps): bump zod from 4.6.5 to 4.6.7');
  });

  it('names a group', () => {
    assert.strictEqual(renderTitle(group, 'main'), 'build(main): bump rollup packages');
  });
});

describe('renderBody', () => {
  const changes = [
    { name: 'nypm', from: ['0.6.10'], to: ['0.6.11'] },
    { name: 'zod', from: ['4.6.5'], to: ['4.6.7'] },
    { name: 'gone', from: ['1.0.0'], to: [] },
  ];

  it('lists every changed package and every moved project', () => {
    const body = renderBody({
      entry: single,
      changes,
      projects: ['packages/utils'],
      cooldownDays: 3,
    });
    assert.match(body, /bumps `zod` from 4\.6\.5 to 4\.6\.7/);
    assert.match(body, /at least 3 days old/);
    assert.match(body, /changed in the lock files \(3\)/);
    assert.match(body, /- `nypm`: 0\.6\.10 -> 0\.6\.11/);
    assert.match(body, /- `gone`: 1\.0\.0 -> removed/);
    assert.match(body, /- `packages\/utils`/);
  });

  it('says so when no project moved', () => {
    const body = renderBody({ entry: group, changes, projects: [], cooldownDays: 3 });
    assert.match(body, /bumps the `rollup` group/);
    assert.match(body, /None\. Only the lock file changed\./);
  });

  it('describes a Terraform constraint change', () => {
    const entry = {
      ecosystem: 'terraform',
      name: 'azurerm',
      isGroup: false,
      members: [{ name: 'azurerm', from: '~> 3', to: '4.9.0', direct: true, data: { major: true } }],
    };
    const body = renderBody({
      entry,
      changes: [{ name: 'azurerm', from: ['~> 3'], to: ['4.9.0'] }],
      projects: ['services/a/deploy/terraform/x/versions.tf'],
      cooldownDays: 3,
    });
    assert.match(body, /changes the version constraint of the provider `azurerm` from `~> 3`/);
    assert.match(body, /release `4\.9\.0` fits/);
    assert.match(body, /This is a major bump/);
    assert.match(body, /Files that changed/);
  });

  it('cuts a long list', () => {
    const many = Array.from({ length: 105 }, (_, index) => ({
      name: `p${index}`,
      from: ['1'],
      to: ['2'],
    }));
    const body = renderBody({ entry: single, changes: many, projects: [], cooldownDays: 3 });
    assert.match(body, /- and 5 more/);
  });
});
