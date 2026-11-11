import assert from 'node:assert';
import { describe, it } from 'node:test';
import { isNotFound, sandboxEnv } from './run.mjs';

describe('sandboxEnv', () => {
  it('drops the tokens and the runner file commands and keeps the rest', () => {
    const saved = { ...process.env };
    Object.assign(process.env, {
      GH_TOKEN: 'a',
      GITHUB_TOKEN: 'b',
      GITHUB_OUTPUT: '/o',
      GITHUB_ENV: '/e',
      ACTIONS_RUNTIME_TOKEN: 'c',
      KEEP_ME: 'yes',
    });
    try {
      const env = sandboxEnv();
      for (const key of [
        'GH_TOKEN',
        'GITHUB_TOKEN',
        'GITHUB_OUTPUT',
        'GITHUB_ENV',
        'ACTIONS_RUNTIME_TOKEN',
      ]) {
        assert.ok(!(key in env), `${key} stays in the environment`);
      }
      assert.strictEqual(env.KEEP_ME, 'yes');
      assert.ok('PATH' in env);
    } finally {
      for (const key of Object.keys(process.env)) {
        if (!(key in saved)) {
          delete process.env[key];
        }
      }
      Object.assign(process.env, saved);
    }
  });
});

describe('isNotFound', () => {
  it('is true for a failed gh call that answers HTTP 404', () => {
    assert.ok(isNotFound({ status: 1, stdout: '', stderr: 'gh: Not Found (HTTP 404)' }));
  });

  it('is false for another failure and for a success', () => {
    assert.ok(!isNotFound({ status: 1, stdout: '', stderr: 'gh: Server Error (HTTP 502)' }));
    assert.ok(!isNotFound({ status: 0, stdout: '3', stderr: '' }));
  });
});
