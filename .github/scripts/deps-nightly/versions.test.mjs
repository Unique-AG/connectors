import assert from 'node:assert';
import { describe, it } from 'node:test';
import {
  compareVersions,
  isMajorBump,
  isStable,
  newestVersion,
  oldestVersion,
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

  it('is false inside one major version and for text that is not a version', () => {
    assert.strictEqual(isMajorBump('0.28.2', '0.29.0'), false);
    assert.strictEqual(isMajorBump(['1.2.0'], ['1.3.0']), false);
    assert.strictEqual(isMajorBump('workspace:*', '2.0.0'), false);
  });
});
