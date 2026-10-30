import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { runOrThrow } from './run.mjs';

export const config = JSON.parse(readFileSync('.github/deps-groups.json', 'utf8'));
export const releaseAge = `--config.minimumReleaseAge=${config.cooldownDays * 24 * 60}`;

export function uvProjectFolders() {
  return ['packages', 'services'].flatMap((parent) =>
    readdirSync(parent)
      .map((name) => `${parent}/${name}`)
      .filter((folder) => existsSync(`${folder}/pyproject.toml`)),
  );
}

export const ACTION_FILES = /^\.github\/(workflows\/[^/]+\.ya?ml|actions\/.+\/action\.ya?ml)$/;
export const DOCKERFILES = /(^|\/)Dockerfile(\.[^/]*)?$/;
export const TERRAFORM_FILES = /(^|\/)versions\.tf$/;
export const TERRAFORM_LOCKS = /(^|\/)\.terraform\.lock\.hcl$/;

export function trackedFiles(pattern) {
  return runOrThrow('git', ['ls-files'])
    .split('\n')
    .filter((path) => pattern.test(path));
}

export function readFiles(paths) {
  return Object.fromEntries(paths.map((path) => [path, readFileSync(path, 'utf8')]));
}
