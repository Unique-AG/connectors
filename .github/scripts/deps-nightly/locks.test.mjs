import assert from 'node:assert';
import { describe, it } from 'node:test';
import {
  changedPackages,
  findDowngrades,
  findMissing,
  hasUvCooldown,
  movedPnpmImporters,
  normalizeName,
  parsePnpmPackages,
  parseRequirements,
  parseUvDryRun,
  parseUvPackages,
  pinEdit,
  pinnedVersion,
  restoreUvLockHeader,
  transitiveUpdates,
  youngVersionOf,
} from './locks.mjs';

const pnpmLock = (zod, nypm) => `lockfileVersion: '9.0'

importers:

  .:
    dependencies:
      zod:
        version: ${zod}

  packages/utils:
    dependencies:
      zod:
        version: 4.6.5

packages:

  '@babel/types@7.29.8':
    resolution: {integrity: sha512-aaa}

  nypm@${nypm}:
    resolution: {integrity: sha512-bbb}

  zod@${zod}:
    resolution: {integrity: sha512-ccc}

snapshots:

  zod@${zod}: {}
`;

const uvLock = (httpx2) => `version = 1
revision = 5

[[package]]
name = "httpx2"
version = "${httpx2}"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "hello-mcp"
version = "0.1.1"
source = { virtual = "." }
`;

describe('parsePnpmPackages', () => {
  it('reads scoped and plain package keys from the packages section only', () => {
    const packages = parsePnpmPackages(pnpmLock('4.6.5', '0.6.10'));
    assert.deepStrictEqual(
      [...packages],
      [
        ['@babel/types', ['7.29.8']],
        ['nypm', ['0.6.10']],
        ['zod', ['4.6.5']],
      ],
    );
  });
});

describe('parseUvPackages', () => {
  it('reads registry packages and skips local ones', () => {
    assert.deepStrictEqual([...parseUvPackages(uvLock('2.14.0'))], [['httpx2', ['2.14.0']]]);
  });

  it('normalizes the package names', () => {
    const lock = `[[package]]
name = "Typing_Extensions"
version = "4.15.0"
source = { registry = "https://pypi.org/simple" }
`;
    assert.deepStrictEqual([...parseUvPackages(lock)], [['typing-extensions', ['4.15.0']]]);
  });
});

describe('changedPackages', () => {
  it('lists the versions that left and arrived for each name', () => {
    const before = parsePnpmPackages(pnpmLock('4.6.5', '0.6.10'));
    const after = parsePnpmPackages(pnpmLock('4.6.7', '0.6.10'));
    assert.deepStrictEqual(changedPackages(before, after), [
      { name: 'zod', from: ['4.6.5'], to: ['4.6.7'] },
    ]);
  });

  it('lists a package that is new or gone', () => {
    const changes = changedPackages(new Map([['old', ['1.0.0']]]), new Map([['new', ['2.0.0']]]));
    assert.deepStrictEqual(changes, [
      { name: 'new', from: [], to: ['2.0.0'] },
      { name: 'old', from: ['1.0.0'], to: [] },
    ]);
  });
});

describe('findDowngrades', () => {
  it('names the packages whose newest version went down', () => {
    const before = new Map([
      ['a', ['2.0.0']],
      ['b', ['1.0.0', '2.0.0']],
      ['c', ['1.0.0']],
    ]);
    const after = new Map([
      ['a', ['1.9.0']],
      ['b', ['2.0.0']],
      ['c', ['1.0.1']],
    ]);
    assert.deepStrictEqual(findDowngrades(before, after), ['a']);
  });
});

describe('movedPnpmImporters', () => {
  it('lists the importers whose block changed', () => {
    const moved = movedPnpmImporters(pnpmLock('4.6.5', '0.6.10'), pnpmLock('4.6.7', '0.6.10'));
    assert.deepStrictEqual(moved, ['.']);
  });

  it('lists nothing when only the packages section changed', () => {
    assert.deepStrictEqual(
      movedPnpmImporters(pnpmLock('4.6.5', '0.6.10'), pnpmLock('4.6.5', '0.6.11')),
      [],
    );
  });
});

describe('parseRequirements', () => {
  it('reads names, extras and specifiers from quoted strings', () => {
    const text = `dependencies = [
    "uvicorn[standard]==0.54.0",
    "fastmcp>=4.1,<5",
    "Typing_Extensions==4.0; python_version > '3.9'",
]
[tool.uv.sources]
mcp-configs = { path = "../mcp-configs" }
`;
    assert.deepStrictEqual(parseRequirements(text), [
      { name: 'uvicorn', spec: '==0.54.0' },
      { name: 'fastmcp', spec: '>=4.1,<5' },
      { name: 'typing-extensions', spec: '==4.0' },
    ]);
  });
});

describe('pinnedVersion', () => {
  it('returns the version of an exact pin only', () => {
    assert.strictEqual(pinnedVersion('==1.2.3'), '1.2.3');
    assert.strictEqual(pinnedVersion('>=1.2.3'), undefined);
  });
});

describe('pinEdit', () => {
  it('changes the pin of one package and keeps extras and markers', () => {
    const text = `    "uvicorn[standard]==0.54.0",
    "uvicorn-extra==0.54.0",
    "Typing_Extensions==4.0; python_version > '3.9'",
`;
    assert.strictEqual(
      pinEdit(pinEdit(text, 'uvicorn', '0.55.0'), 'typing-extensions', '4.1'),
      `    "uvicorn[standard]==0.55.0",
    "uvicorn-extra==0.54.0",
    "Typing_Extensions==4.1; python_version > '3.9'",
`,
    );
  });

  it('leaves a range untouched', () => {
    const text = '    "fastmcp>=4.1,<5",\n';
    assert.strictEqual(pinEdit(text, 'fastmcp', '5.0.0'), text);
  });
});

describe('restoreUvLockHeader', () => {
  it('removes the exclude-newer options and keeps the old revision', () => {
    const before = 'version = 1\nrevision = 5\nrequires-python = ">=3.14"\n';
    const after = `version = 1
revision = 3
requires-python = ">=3.14"

[options]
exclude-newer = "0001-01-01T00:00:00Z" # This has no effect.
exclude-newer-span = "P3D"

[[package]]
name = "a"
`;
    assert.strictEqual(
      restoreUvLockHeader(after, before),
      'version = 1\nrevision = 5\nrequires-python = ">=3.14"\n\n[[package]]\nname = "a"\n',
    );
  });
});

describe('parseUvDryRun', () => {
  it('groups the update lines by project', () => {
    const output = `
== packages/a: uv lock --upgrade --dry-run
Resolved 3 packages in 1ms
Update tomlkit v0.15.1 -> v0.15.2

== services/b: uv lock --upgrade --dry-run
Resolved 3 packages in 1ms
`;
    assert.deepStrictEqual(
      [...parseUvDryRun(output)],
      [
        ['packages/a', [{ name: 'tomlkit', from: '0.15.1', to: '0.15.2' }]],
        ['services/b', []],
      ],
    );
  });
});

describe('hasUvCooldown', () => {
  it('finds an exclude-newer setting in any project', () => {
    assert.strictEqual(hasUvCooldown('[tool.uv]\nexclude-newer = "3 days"\n'), true);
    assert.strictEqual(hasUvCooldown('[tool.uv]\npackage = false\n'), false);
  });
});

describe('normalizeName', () => {
  it('lowercases and joins separators with a dash', () => {
    assert.strictEqual(normalizeName('Typing_Extensions.Core'), 'typing-extensions-core');
  });
});

describe('findMissing', () => {
  it('lists the names that a lock lost', () => {
    const lock = new Map([['ruff', ['0.17.2']]]);
    assert.deepStrictEqual(findMissing(lock, ['ruff', 'httpx']), ['httpx']);
  });
});

const YOUNG_OUTPUT =
  'ERR_PNPM_NO_MATURE_MATCHING_VERSION  Version 7.1.2 (released 44 hours ago) of @azure/msal-node does not meet the minimumReleaseAge constraint\n';

describe('youngVersionOf', () => {
  it('returns the package name of a minimumReleaseAge failure', () => {
    assert.strictEqual(youngVersionOf(YOUNG_OUTPUT), '@azure/msal-node');
  });

  it('returns null for another pnpm error', () => {
    assert.strictEqual(
      youngVersionOf('ERR_PNPM_FETCH_404  GET https://registry/zod: Not Found'),
      null,
    );
  });
});

describe('transitiveUpdates', () => {
  const lockOf = (version) => pnpmLock(version, '0.2.1');

  it('lists the lock changes when the update succeeded', () => {
    const { lockChanges, needsPerson } = transitiveUpdates({
      result: { status: 0, stdout: '', stderr: '' },
      before: lockOf('4.6.5'),
      after: lockOf('4.6.7'),
      cooldownDays: 3,
    });
    assert.deepStrictEqual(lockChanges, [{ name: 'zod', from: ['4.6.5'], to: ['4.6.7'] }]);
    assert.deepStrictEqual(needsPerson, []);
  });

  it('drops the lock changes and asks for a person when only young versions match', () => {
    const { lockChanges, needsPerson } = transitiveUpdates({
      result: { status: 1, stdout: '', stderr: YOUNG_OUTPUT },
      before: lockOf('4.6.5'),
      after: lockOf('4.6.5'),
      cooldownDays: 3,
    });
    assert.deepStrictEqual(lockChanges, []);
    assert.strictEqual(needsPerson.length, 1);
    assert.strictEqual(needsPerson[0].ecosystem, 'npm');
    assert.strictEqual(needsPerson[0].name, '@azure/msal-node');
    assert.match(needsPerson[0].reason, /younger than 3 days/);
  });

  it('throws with the output on any other failure', () => {
    assert.throws(
      () =>
        transitiveUpdates({
          result: { status: 1, stdout: '', stderr: 'ERR_PNPM_OTHER boom' },
          before: '',
          after: '',
          cooldownDays: 3,
        }),
      /ERR_PNPM_OTHER boom/,
    );
  });
});
