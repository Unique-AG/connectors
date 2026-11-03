import assert from 'node:assert';
import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, it } from 'node:test';
import {
  generateLock,
  LOCK_FILE,
  mergeLockBlock,
  normalizeConstraint,
  parseLock,
  providerAddress,
} from './terraform-lock.mjs';

const HEADER = `# This file is maintained automatically by "terraform init".
# Manual edits may be lost in future updates.

`;
const block = (type, version, constraints) => `provider "registry.terraform.io/hashicorp/${type}" {
  version     = "${version}"
  constraints = "${constraints}"
  hashes = [
    "h1:${type}${version}=",
    "zh:${type}${version}",
  ]
}
`;
const lock = (...blocks) => HEADER + blocks.join('\n');

describe('providerAddress', () => {
  it('adds the public registry to a two part source', () => {
    assert.strictEqual(
      providerAddress('hashicorp/azurerm'),
      'registry.terraform.io/hashicorp/azurerm',
    );
    assert.strictEqual(providerAddress('example.com/team/thing'), 'example.com/team/thing');
  });
});

describe('parseLock', () => {
  it('reads the locked version of each provider', () => {
    const text = lock(block('azurerm', '4.9.0', '>= 4, < 6'), block('time', '0.13.1', '~> 0.13'));
    assert.deepStrictEqual(
      [...parseLock(text)],
      [
        ['registry.terraform.io/hashicorp/azurerm', '4.9.0'],
        ['registry.terraform.io/hashicorp/time', '0.13.1'],
      ],
    );
  });

  it('returns no providers for a missing file', () => {
    assert.deepStrictEqual([...parseLock(undefined)], []);
  });
});

describe('normalizeConstraint', () => {
  for (const [constraint, expected] of [
    ['~> 3', '~> 3.0'],
    ['~> 3.0', '~> 3.0'],
    ['~> 0.12', '~> 0.12'],
    ['~> 4.1.2', '~> 4.1.2'],
    ['>= 4, < 6', '>= 4.0.0, < 6.0.0'],
    ['< 6, >= 4', '>= 4.0.0, < 6.0.0'],
    ['>= 4,<6', '>= 4.0.0, < 6.0.0'],
    ['>= 1.2', '>= 1.2.0'],
    ['= 1.2.3', '1.2.3'],
    ['1.2.3', '1.2.3'],
    ['> 1', '> 1.0.0'],
    ['<= 2.5', '<= 2.5.0'],
    ['!= 4.9.0, >= 4', '>= 4.0.0, != 4.9.0'],
    ['>= 1.0, < 2.0, != 1.5', '>= 1.0.0, != 1.5.0, < 2.0.0'],
    ['< 5, <= 5', '<= 5.0.0, < 5.0.0'],
    ['>= 1, > 1', '> 1.0.0, >= 1.0.0'],
    ['~> 3, != 3.5', '~> 3.0, != 3.5.0'],
    ['< 6, < 5, >= 1', '>= 1.0.0, < 5.0.0, < 6.0.0'],
    ['<= 9, ~> 3.1', '~> 3.1, <= 9.0.0'],
  ]) {
    it(`writes ${constraint} as Terraform does`, () => {
      assert.strictEqual(normalizeConstraint(constraint), expected);
    });
  }
});

describe('mergeLockBlock', () => {
  const generated = lock(block('azurerm', '4.9.0', '4.9.0'));

  it('replaces the block of the provider, keeps the others, and sets the real constraint', () => {
    const existing = lock(
      block('azurerm', '4.5.0', '>= 4.0.0, < 6.0.0'),
      block('time', '0.13.1', '~> 0.13'),
    );
    assert.strictEqual(
      mergeLockBlock(existing, generated, '>= 4, < 6'),
      lock(block('azurerm', '4.9.0', '>= 4.0.0, < 6.0.0'), block('time', '0.13.1', '~> 0.13')),
    );
  });

  it('inserts a new provider in alphabetical order', () => {
    const existing = lock(block('time', '0.13.1', '~> 0.13'));
    const merged = mergeLockBlock(existing, generated, '>= 4, < 6');
    assert.deepStrictEqual(
      [...parseLock(merged).keys()],
      ['registry.terraform.io/hashicorp/azurerm', 'registry.terraform.io/hashicorp/time'],
    );
  });

  it('creates the file, with the header, when there is none', () => {
    assert.strictEqual(
      mergeLockBlock(null, generated, '>= 4, < 6'),
      lock(block('azurerm', '4.9.0', '>= 4.0.0, < 6.0.0')),
    );
  });

  it('changes nothing when the lock already holds the block', () => {
    const existing = lock(block('azurerm', '4.9.0', '>= 4.0.0, < 6.0.0'));
    assert.strictEqual(mergeLockBlock(existing, generated, '>= 4, < 6'), existing);
  });

  it('rejects output with no provider block', () => {
    assert.throws(() => mergeLockBlock(null, HEADER, '~> 1'), /wrote no provider block/);
  });
});

describe('generateLock', () => {
  it('runs terraform for one pinned provider and every platform, then reads the lock', () => {
    const calls = [];
    const text = generateLock({
      source: 'hashicorp/azurerm',
      version: '4.9.0',
      platforms: ['linux_amd64', 'darwin_arm64'],
      terraform: (args, cwd) => {
        calls.push(args);
        writeFileSync(join(cwd, LOCK_FILE), lock(block('azurerm', '4.9.0', '4.9.0')));
      },
    });
    assert.deepStrictEqual(calls, [
      ['providers', 'lock', '-platform=linux_amd64', '-platform=darwin_arm64'],
    ]);
    assert.match(text, /version     = "4\.9\.0"/);
  });
});
