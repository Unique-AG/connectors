import assert from 'node:assert';
import { describe, it } from 'node:test';
import { classifyOpenPull, closedKeysOf, entryKey, markerKeyOf, markerOf } from './state.mjs';

const entry = (to) => ({
  slug: 'npm-nestjs',
  members: [
    { name: '@nestjs/core', to },
    { name: '@nestjs/common', to },
  ],
});

describe('entryKey', () => {
  it('changes with a target version and not with the order of the members', () => {
    const reversed = { ...entry('11.2.4'), members: [...entry('11.2.4').members].reverse() };
    assert.strictEqual(entryKey(entry('11.2.4')), entryKey(reversed));
    assert.notStrictEqual(entryKey(entry('11.2.4')), entryKey(entry('11.2.5')));
    assert.match(entryKey(entry('11.2.4')), /^npm-nestjs:[0-9a-f]{12}$/);
  });
});

describe('markers', () => {
  it('reads the key back from a pull request body and ignores a body with no marker', () => {
    const key = entryKey(entry('11.2.4'));
    assert.strictEqual(markerKeyOf(`text\n\n${markerOf(key)}\n`), key);
    assert.strictEqual(markerKeyOf('no marker'), null);
    assert.strictEqual(markerKeyOf(null), null);
    assert.deepStrictEqual(closedKeysOf([markerOf(key), 'none', null]), new Set([key]));
  });
});

describe('classifyOpenPull', () => {
  const key = entryKey(entry('11.2.4'));
  const pull = { body: markerOf(key), behindBy: 3, humanCommits: false, labels: [] };

  it('keeps a pull request that is up to date', () => {
    assert.strictEqual(classifyOpenPull({ key, pull: { ...pull, behindBy: 0 } }), 'keep');
  });

  it('rebuilds a pull request that nobody touched', () => {
    assert.strictEqual(classifyOpenPull({ key, pull }), 'rebuild');
  });

  it('only merges main into a pull request that has a commit from a person', () => {
    assert.strictEqual(classifyOpenPull({ key, pull: { ...pull, humanCommits: true } }), 'update');
  });

  for (const label of ['ai-assisted', 'human-required']) {
    it(`only merges main into a pull request that carries the label ${label}`, () => {
      assert.strictEqual(
        classifyOpenPull({ key, pull: { ...pull, labels: ['dependencies', label] } }),
        'update',
      );
    });
  }

  it('replaces a pull request for other versions, and one with no marker', () => {
    assert.strictEqual(classifyOpenPull({ key: entryKey(entry('11.3.0')), pull }), 'replace');
    assert.strictEqual(classifyOpenPull({ key, pull: { ...pull, body: '' } }), 'replace');
  });
});
