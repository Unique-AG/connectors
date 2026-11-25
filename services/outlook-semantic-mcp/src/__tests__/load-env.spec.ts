import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

const LOAD_ENV = resolve(__dirname, '../load-env.ts');
const PRINT_ENV = 'console.log(JSON.stringify({ a: process.env.A, b: process.env.B }))';

const run = (cwd: string, env: NodeJS.ProcessEnv) => {
  const { stdout, stderr, status } = spawnSync(
    process.execPath,
    ['--no-warnings', '--import', LOAD_ENV, '-e', PRINT_ENV],
    { cwd, env: { PATH: process.env.PATH, ...env }, encoding: 'utf8' },
  );
  expect(stderr).toBe('');
  expect(status).toBe(0);
  return JSON.parse(stdout);
};

describe('load-env', () => {
  let cwd: string;

  beforeEach(() => {
    cwd = mkdtempSync(join(tmpdir(), 'load-env-'));
    writeFileSync(join(cwd, '.env'), 'A=from_env_file\nB=from_env_file\n');
    writeFileSync(join(cwd, '.env.test'), 'A=from_test_file\nB=from_test_file\n');
  });

  afterEach(() => {
    rmSync(cwd, { recursive: true, force: true });
  });

  it('loads .env before anything else runs, in production too', () => {
    expect(run(cwd, { NODE_ENV: 'production' })).toEqual({
      a: 'from_env_file',
      b: 'from_env_file',
    });
  });

  it('keeps a variable that is already set', () => {
    expect(run(cwd, { A: 'from_shell' })).toEqual({ a: 'from_shell', b: 'from_env_file' });
  });

  it('loads .env.test when NODE_ENV is test', () => {
    expect(run(cwd, { NODE_ENV: 'test' })).toEqual({
      a: 'from_test_file',
      b: 'from_test_file',
    });
  });

  it('does nothing without an env file', () => {
    rmSync(join(cwd, '.env'));

    expect(run(cwd, {})).toEqual({});
  });
});
