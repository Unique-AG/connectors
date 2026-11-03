import { spawnSync } from 'node:child_process';

export function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    encoding: 'utf8',
    maxBuffer: 256 * 1024 * 1024,
    ...options,
  });
  return {
    status: result.status ?? 1,
    stdout: result.stdout ?? '',
    stderr: result.stderr ?? '',
  };
}

export function runOrThrow(command, args, options = {}) {
  const result = run(command, args, options);
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(' ')} failed:\n${result.stdout}${result.stderr}`);
  }
  return result.stdout;
}

const PRIVILEGED =
  /^(GH_TOKEN|GITHUB_TOKEN|GITHUB_(OUTPUT|ENV|PATH|STATE|STEP_SUMMARY)|ACTIONS_.+)$/;

export function sandboxEnv() {
  return Object.fromEntries(Object.entries(process.env).filter(([key]) => !PRIVILEGED.test(key)));
}
