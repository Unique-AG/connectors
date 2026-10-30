import assert from 'node:assert';
import { describe, it } from 'node:test';
import { createNpmDeprecationLookup, dropDeprecated } from './npm-deprecated.mjs';

const npm = (name, to) => ({ ecosystem: 'npm', name, from: '1.0.0', to, direct: true });

describe('createNpmDeprecationLookup', () => {
  const answer = (body, status = 200) => ({ status, json: async () => body });

  it('returns the deprecation message and encodes a scoped name', async () => {
    let seen;
    const fetchImpl = async (url, options) => {
      seen = { url, options };
      return answer({ version: '2.0.0', deprecated: 'Use 3.x.' });
    };
    const message = await createNpmDeprecationLookup(fetchImpl).deprecated('@nestjs/core', '2.0.0');
    assert.strictEqual(message, 'Use 3.x.');
    assert.strictEqual(seen.url, 'https://registry.npmjs.org/@nestjs%2Fcore/2.0.0');
    assert.ok(seen.options.signal instanceof AbortSignal);
  });

  it('returns null for a version that is not deprecated', async () => {
    const fetchImpl = async () => answer({ version: '2.0.0' });
    assert.strictEqual(
      await createNpmDeprecationLookup(fetchImpl).deprecated('zod', '2.0.0'),
      null,
    );
  });

  it('returns null on a 404 answer without a retry', async () => {
    let calls = 0;
    const fetchImpl = async () => {
      calls++;
      return answer({ deprecated: 'Use 3.x.' }, 404);
    };
    assert.strictEqual(
      await createNpmDeprecationLookup(fetchImpl).deprecated('zod', '2.0.0'),
      null,
    );
    assert.strictEqual(calls, 1);
  });

  it('retries once after a 429 answer', async () => {
    const answers = [answer({}, 429), answer({ deprecated: 'Use 3.x.' })];
    const fetchImpl = async () => answers.shift();
    assert.strictEqual(
      await createNpmDeprecationLookup(fetchImpl).deprecated('zod', '2.0.0'),
      'Use 3.x.',
    );
  });

  it('returns undefined after two 429 answers', async () => {
    let calls = 0;
    const fetchImpl = async () => {
      calls++;
      return answer({}, 429);
    };
    assert.strictEqual(
      await createNpmDeprecationLookup(fetchImpl).deprecated('zod', '2.0.0'),
      undefined,
    );
    assert.strictEqual(calls, 2);
  });

  it('returns undefined after two network errors', async () => {
    const fetchImpl = async () => {
      throw new Error('offline');
    };
    assert.strictEqual(
      await createNpmDeprecationLookup(fetchImpl).deprecated('zod', '2.0.0'),
      undefined,
    );
  });
});

describe('dropDeprecated', () => {
  const lookupOf = (deprecations) => {
    const calls = [];
    return {
      calls,
      deprecated: async (name, version) => {
        calls.push(`${name}@${version}`);
        return deprecations[`${name}@${version}`] ?? null;
      },
    };
  };

  it('moves a deprecated target to needsPerson and keeps the rest', async () => {
    const lookup = lookupOf({ 'old@2.0.0': 'Use new instead.' });
    const result = await dropDeprecated({
      candidates: [npm('old', '2.0.0'), npm('fresh', '1.1.0')],
      lookup,
    });
    assert.deepStrictEqual(result, {
      candidates: [npm('fresh', '1.1.0')],
      needsPerson: [
        {
          ecosystem: 'npm',
          name: 'old',
          reason: 'The version 2.0.0 is deprecated: Use new instead.',
        },
      ],
    });
  });

  it('looks up a scoped name as given', async () => {
    const lookup = lookupOf({ '@scope/pkg@3.0.0': 'Moved.' });
    const { candidates, needsPerson } = await dropDeprecated({
      candidates: [npm('@scope/pkg', '3.0.0')],
      lookup,
    });
    assert.deepStrictEqual(candidates, []);
    assert.strictEqual(needsPerson[0].name, '@scope/pkg');
  });

  it('checks every version of a comma list and names the deprecated one', async () => {
    const lookup = lookupOf({ 'lib@1.2.4': 'Broken.' });
    const { candidates, needsPerson } = await dropDeprecated({
      candidates: [npm('lib', '1.2.3, 1.2.4')],
      lookup,
    });
    assert.deepStrictEqual(lookup.calls, ['lib@1.2.3', 'lib@1.2.4']);
    assert.deepStrictEqual(candidates, []);
    assert.strictEqual(needsPerson[0].reason, 'The version 1.2.4 is deprecated: Broken.');
  });

  it('truncates a long message to 120 characters', async () => {
    const lookup = lookupOf({ 'old@2.0.0': 'x'.repeat(300) });
    const { needsPerson } = await dropDeprecated({ candidates: [npm('old', '2.0.0')], lookup });
    assert.strictEqual(
      needsPerson[0].reason,
      `The version 2.0.0 is deprecated: ${'x'.repeat(120)}`,
    );
  });

  it('passes a non-npm candidate through without a lookup', async () => {
    const lookup = lookupOf({ 'azurerm@4.9.0': 'Nope.' });
    const candidate = { ecosystem: 'terraform', name: 'azurerm', from: '~> 3', to: '4.9.0' };
    const result = await dropDeprecated({ candidates: [candidate], lookup });
    assert.deepStrictEqual(result, { candidates: [candidate], needsPerson: [] });
    assert.deepStrictEqual(lookup.calls, []);
  });

  it('keeps a candidate when the registry says it is not deprecated', async () => {
    const candidate = npm('zod', '4.1.0');
    const result = await dropDeprecated({ candidates: [candidate], lookup: lookupOf({}) });
    assert.deepStrictEqual(result, { candidates: [candidate], needsPerson: [] });
  });

  it('moves a candidate to needsPerson when the registry gives no answer', async () => {
    const lookup = { deprecated: async (name) => (name === 'down' ? undefined : null) };
    const result = await dropDeprecated({
      candidates: [npm('down', '1.1.0'), npm('zod', '4.1.0')],
      lookup,
    });
    assert.deepStrictEqual(result, {
      candidates: [npm('zod', '4.1.0')],
      needsPerson: [
        {
          ecosystem: 'npm',
          name: 'down',
          reason:
            'The npm registry did not answer for 1.1.0. The job cannot check whether it is deprecated.',
        },
      ],
    });
  });

  it('keeps the deprecation reason when another version of the candidate gets no answer', async () => {
    const lookup = {
      deprecated: async (_, version) => (version === '1.2.3' ? undefined : 'Broken.'),
    };
    const { needsPerson } = await dropDeprecated({
      candidates: [npm('lib', '1.2.3, 1.2.4')],
      lookup,
    });
    assert.strictEqual(needsPerson[0].reason, 'The version 1.2.4 is deprecated: Broken.');
  });

  it('runs at most 8 lookups at once', async () => {
    let active = 0;
    let peak = 0;
    const lookup = {
      deprecated: async () => {
        peak = Math.max(peak, ++active);
        await new Promise((resolve) => setTimeout(resolve, 2));
        active--;
        return null;
      },
    };
    const candidates = Array.from({ length: 30 }, (_, index) => npm(`pkg-${index}`, '1.0.1'));
    const result = await dropDeprecated({ candidates, lookup });
    assert.strictEqual(result.candidates.length, 30);
    assert.strictEqual(peak, 8);
  });
});
