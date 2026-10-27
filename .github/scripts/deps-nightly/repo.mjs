import { existsSync, readdirSync, readFileSync } from 'node:fs';

export const config = JSON.parse(readFileSync('.github/deps-groups.json', 'utf8'));
export const releaseAge = `--config.minimumReleaseAge=${config.cooldownDays * 24 * 60}`;

export function uvProjectFolders() {
  return ['packages', 'services'].flatMap((parent) =>
    readdirSync(parent)
      .map((name) => `${parent}/${name}`)
      .filter((folder) => existsSync(`${folder}/pyproject.toml`)),
  );
}
