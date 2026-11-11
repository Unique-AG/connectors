import assert from 'node:assert';
import { describe, it } from 'node:test';
import { pnpmCommands, renderBody, renderTitle, uvLockArgs, withOverrides } from './bump.mjs';

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

  it('updates only the direct members', () => {
    const commands = pnpmCommands(group, RELEASE_AGE);
    assert.deepStrictEqual(
      commands.map((command) => [command.includes('--latest'), command.at(-1)]),
      [[true, 'rollup']],
    );
  });

  it('runs no command for an entry with no direct member', () => {
    const indirect = { ...single, members: [{ ...single.members[0], direct: false }] };
    assert.deepStrictEqual(pnpmCommands(indirect, RELEASE_AGE), []);
  });
});

describe('withOverrides', () => {
  const packageJson = JSON.stringify({ name: 'root', pnpm: { overrides: { esbuild: '0.28.2' } } });
  const held = (entries) => new Map(Object.entries(entries));

  it('pins a package that the lock holds once by its name, and keeps the other overrides', () => {
    const text = withOverrides(
      packageJson,
      [{ name: 'qs', from: '6.17.0', to: '6.17.1' }],
      held({ qs: ['6.17.0'] }),
    );
    assert.deepStrictEqual(JSON.parse(text).pnpm.overrides, { esbuild: '0.28.2', qs: '6.17.1' });
  });

  it('pins a 0.x minor bump of a package that the lock holds once', () => {
    const text = withOverrides(
      '{"name":"root"}',
      [{ name: 'types', from: '0.155.0', to: '0.156.0' }],
      held({ types: ['0.155.0'] }),
    );
    assert.deepStrictEqual(JSON.parse(text).pnpm.overrides, { types: '0.156.0' });
  });

  it('adds one pin for each version line of a package that the lock holds twice', () => {
    const text = withOverrides(
      '{"name":"root"}',
      [{ name: 'parser', from: '7.29.11, 8.0.8', to: '7.29.12, 8.0.10' }],
      held({ parser: ['7.29.11', '8.0.8'] }),
    );
    assert.deepStrictEqual(JSON.parse(text).pnpm.overrides, {
      'parser@>=7.0.0 <8.0.0': '7.29.12',
      'parser@>=8.0.0 <9.0.0': '8.0.10',
    });
  });

  it('limits a 0.x version to its minor line when the lock holds two versions', () => {
    const text = withOverrides(
      '{"name":"root"}',
      [{ name: 'confbox', from: '0.3.1', to: '0.3.2' }],
      held({ confbox: ['0.2.4', '0.3.1'] }),
    );
    assert.deepStrictEqual(JSON.parse(text).pnpm.overrides, {
      'confbox@>=0.3.0 <0.4.0': '0.3.2',
    });
  });

  it('throws when the lock holds two versions and the new one has no old version on its line', () => {
    assert.throws(
      () =>
        withOverrides(
          '{"name":"root"}',
          [{ name: 'qs', from: '6.17.0', to: '7.0.0' }],
          held({ qs: ['6.17.0', '5.0.0'] }),
        ),
      /no old version on the same line/,
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

  it('pairs the versions of a package that the lock holds in several versions', () => {
    const several = {
      ...single,
      name: 'parser',
      members: [{ name: 'parser', from: '7.1.0, 8.0.0', to: '7.1.1, 8.0.1', direct: false }],
    };
    assert.strictEqual(
      renderTitle(several, 'deps'),
      'build(deps): bump parser from 7.1.0 to 7.1.1 and from 8.0.0 to 8.0.1',
    );
  });
});

describe('renderBody', () => {
  const changes = [
    { name: 'parser', from: ['7.1.0', '8.0.0'], to: ['7.1.1', '8.0.1'] },
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
    assert.match(body, /^Bump `zod` from 4\.6\.5 to 4\.6\.7/);
    assert.match(body, /at least 3 days old/);
    assert.match(body, /changed in the lock files \(4\)/);
    assert.match(body, /- `parser`: 7\.1\.0 -> 7\.1\.1, 8\.0\.0 -> 8\.0\.1/);
    assert.match(body, /- `nypm`: 0\.6\.10 -> 0\.6\.11/);
    assert.match(body, /- `gone`: 1\.0\.0 -> removed/);
    assert.match(body, /- `packages\/utils`/);
  });

  it('keeps the text for the commit above the line `---` and the rest below it', () => {
    const entry = { ...single, key: 'npm-zod:0123456789ab', members: [{ ...single.members[0], data: { major: true } }] };
    const body = renderBody({ entry, changes, projects: ['packages/utils'], cooldownDays: 3 });
    const [commit, rest] = body.split('\n---\n');
    assert.match(commit, /^Bump `zod` from 4\.6\.5 to 4\.6\.7\.\n\nPackages that changed in the lock files \(4\):\n/);
    assert.match(commit, /- `gone`: 1\.0\.0 -> removed/);
    assert.doesNotMatch(commit, /nightly dependency job|major bump|Projects that moved|deps-nightly/);
    assert.match(rest, /nightly dependency job/);
    assert.match(rest, /This is a major bump/);
    assert.match(rest, /- `packages\/utils`/);
    assert.match(rest, /deps-nightly:npm-zod:0123456789ab/);
  });

  it('ends with the marker that holds the key of the entry', () => {
    const body = renderBody({
      entry: { ...single, key: 'npm-zod:0123456789ab' },
      changes,
      projects: [],
      cooldownDays: 3,
    });
    assert.match(body, /<!-- deps-nightly:npm-zod:0123456789ab -->\n$/);
  });

  it('says so when no project moved', () => {
    const body = renderBody({ entry: group, changes, projects: [], cooldownDays: 3 });
    assert.match(body, /^Bump the `rollup` group/);
    assert.match(body, /None\. Only the lock file changed\./);
  });

  it('describes a Terraform constraint change', () => {
    const entry = {
      ecosystem: 'terraform',
      name: 'azurerm',
      isGroup: false,
      members: [
        { name: 'azurerm', from: '~> 3', to: '4.9.0', direct: true, data: { major: true } },
      ],
    };
    const body = renderBody({
      entry,
      changes: [{ name: 'azurerm', from: ['~> 3'], to: ['4.9.0'] }],
      projects: ['services/a/deploy/terraform/x/versions.tf'],
      cooldownDays: 3,
    });
    assert.match(body, /^Change the version constraint of the provider `azurerm` from `~> 3`/);
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
