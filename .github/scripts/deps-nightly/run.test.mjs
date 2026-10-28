import assert from 'node:assert';
import { describe, it } from 'node:test';
import { sandboxEnv } from './run.mjs';

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
