import assert from 'node:assert';
import { describe, it } from 'node:test';
import {
  compareVersions,
  formatChange,
  isMajorBump,
  isStable,
  newestVersion,
  oldestVersion,
  pairVersions,
  updateType,
  versionLine,
} from './versions.mjs';

describe('compareVersions', () => {
  it('orders numeric parts as numbers', () => {
    assert.strictEqual(compareVersions('1.10.0', '1.9.9'), 1);
    assert.strictEqual(compareVersions('2.0.0', '10.0.0'), -1);
  });

  it('treats missing parts as zero', () => {
    assert.strictEqual(compareVersions('1.2', '1.2.0'), 0);
  });

  it('puts a pre-release before its release', () => {
    assert.strictEqual(compareVersions('2.0.0rc1', '2.0.0'), -1);
    assert.strictEqual(compareVersions('2.0.0-beta.2', '2.0.0-beta.10'), -1);
  });

  it('puts a post release after its release', () => {
    assert.strictEqual(compareVersions('2.9.0.post0', '2.9.0'), 1);
    assert.strictEqual(compareVersions('2.9.0.post0', '3.0.0'), -1);
  });

  it('throws for text that is not a version', () => {
    assert.throws(() => compareVersions('latest', '1.0.0'), /Not a version/);
  });
});

describe('isStable', () => {
  it('accepts releases and post releases', () => {
    assert.strictEqual(isStable('1.2.3'), true);
    assert.strictEqual(isStable('1.2.3.post1'), true);
  });

  it('rejects pre-releases and text that is not a version', () => {
    assert.strictEqual(isStable('1.2.3rc1'), false);
    assert.strictEqual(isStable('1.2.3.dev4'), false);
    assert.strictEqual(isStable('abc'), false);
  });
});

describe('newestVersion and oldestVersion', () => {
  it('pick the edges of a list without changing it', () => {
    const versions = ['1.2.0', '1.10.0', '1.9.0'];
    assert.strictEqual(newestVersion(versions), '1.10.0');
    assert.strictEqual(oldestVersion(versions), '1.2.0');
    assert.deepStrictEqual(versions, ['1.2.0', '1.10.0', '1.9.0']);
  });
});

describe('isMajorBump', () => {
  it('is true when a target has a higher first number', () => {
    assert.strictEqual(isMajorBump('4.6.5', '5.0.0'), true);
    assert.strictEqual(isMajorBump(['8.1.0', '9.0.0'], ['10.0.0']), true);
  });

  it('is false when each version line of a package moves inside its own major', () => {
    assert.strictEqual(isMajorBump(['7.29.11', '8.0.8'], ['7.29.12', '8.0.10']), false);
  });

  it('is false for a downgrade', () => {
    assert.strictEqual(isMajorBump('2.0.0', '1.9.0'), false);
  });

  it('is false inside one major version and for text that is not a version', () => {
    assert.strictEqual(isMajorBump('0.28.2', '0.29.0'), false);
    assert.strictEqual(isMajorBump(['1.2.0'], ['1.3.0']), false);
    assert.strictEqual(isMajorBump('workspace:*', '2.0.0'), false);
  });
});

describe('versionLine', () => {
  it('gives the range of the major, or of the minor for 0.x', () => {
    assert.strictEqual(versionLine('7.29.11'), '>=7.0.0 <8.0.0');
    assert.strictEqual(versionLine('0.3.1'), '>=0.3.0 <0.4.0');
    assert.strictEqual(versionLine('0.0.4'), '>=0.0.4 <0.0.5');
  });
});

describe('pairVersions and formatChange', () => {
  it('pairs each old version with the new version on its line', () => {
    assert.deepStrictEqual(pairVersions('7.29.11, 8.0.8', '7.29.12, 8.0.10'), [
      ['7.29.11', '7.29.12'],
      ['8.0.8', '8.0.10'],
    ]);
  });

  it('writes one arrow for each pair', () => {
    assert.strictEqual(
      formatChange(['7.29.11', '8.0.8'], ['7.29.12', '8.0.10']),
      '7.29.11 -> 7.29.12, 8.0.8 -> 8.0.10',
    );
  });

  it('keeps a single change, and text that is not a version', () => {
    assert.strictEqual(formatChange('4.6.5', '4.6.7'), '4.6.5 -> 4.6.7');
    assert.strictEqual(formatChange('~> 3', '4.9.0'), '~> 3 -> 4.9.0');
  });

  it('keeps a Terraform constraint list whole', () => {
    assert.strictEqual(formatChange('>= 4, < 6', '6.1.0'), '>= 4, < 6 -> 6.1.0');
    assert.deepStrictEqual(pairVersions('>= 4, < 6 and ~> 0.12', '6.1.0'), [
      ['>= 4, < 6 and ~> 0.12', '6.1.0'],
    ]);
  });

  it('pairs a new major with the newest older version', () => {
    assert.deepStrictEqual(pairVersions('6.1.0, 7.0.0', '8.0.0'), [['7.0.0', '8.0.0']]);
  });
});

describe('updateType', () => {
  it('names the first part that changes', () => {
    assert.strictEqual(updateType('4.6.5', '5.0.0'), 'major');
    assert.strictEqual(updateType('4.6.5', '4.7.0'), 'minor');
    assert.strictEqual(updateType('4.6.5', '4.6.7'), 'patch');
    assert.strictEqual(updateType('v1.2', '1.2.1'), 'patch');
  });

  it('is unknown for text that is not a version', () => {
    assert.strictEqual(updateType('main', '1.0.0'), 'unknown');
  });
});
