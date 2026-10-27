import assert from 'node:assert';
import { appendFileSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { applyActions } from './actions.mjs';
import { pnpmCommands, renderBody, renderTitle, uvLockArgs } from './bump.mjs';
import { applyDocker } from './docker.mjs';
import {
  changedPackages,
  findDowngrades,
  hasUvCooldown,
  movedPnpmImporters,
  normalizeName,
  parsePnpmPackages,
  parseUvPackages,
  pinEdit,
  restoreUvLockHeader,
} from './locks.mjs';
import {
  ACTION_FILES,
  config,
  DOCKERFILES,
  readFiles,
  releaseAge,
  trackedFiles,
  uvProjectFolders,
} from './repo.mjs';
import { run, runOrThrow } from './run.mjs';
import { commitScope } from './scope.mjs';
import { compareVersions, newestVersion } from './versions.mjs';

const entry = JSON.parse(process.env.ENTRY);

function bumpNpm() {
  const before = readFileSync('pnpm-lock.yaml', 'utf8');
  for (const [command, ...args] of pnpmCommands(entry, releaseAge)) {
    runOrThrow(command, args);
  }
  runOrThrow('pnpm', ['dedupe', '--ignore-scripts', '--loglevel', 'error', releaseAge]);
  const after = readFileSync('pnpm-lock.yaml', 'utf8');
  return {
    changes: changedPackages(parsePnpmPackages(before), parsePnpmPackages(after)),
    projects: movedPnpmImporters(before, after),
  };
}

function bumpUv() {
  const folders = uvProjectFolders();
  const pyprojects = new Map(
    folders.map((folder) => [folder, readFileSync(`${folder}/pyproject.toml`, 'utf8')]),
  );
  const cooldownFlag = hasUvCooldown([...pyprojects.values()])
    ? []
    : ['--exclude-newer', `${config.cooldownDays} days`];
  for (const [folder, text] of pyprojects) {
    const edited = entry.members.reduce(
      (current, { name, to }) => pinEdit(current, normalizeName(name), to),
      text,
    );
    if (edited !== text) {
      writeFileSync(`${folder}/pyproject.toml`, edited);
    }
  }
  const changes = [];
  const projects = [];
  for (const folder of folders) {
    const before = readFileSync(`${folder}/uv.lock`, 'utf8');
    const held = parseUvPackages(before);
    const behind = entry.members.filter(
      ({ name, to }) => held.has(name) && compareVersions(newestVersion(held.get(name)), to) < 0,
    );
    if (behind.length === 0) {
      continue;
    }
    runOrThrow('uv', uvLockArgs(behind, cooldownFlag), { cwd: folder });
    const after = restoreUvLockHeader(readFileSync(`${folder}/uv.lock`, 'utf8'), before);
    writeFileSync(`${folder}/uv.lock`, after);
    const downgrades = findDowngrades(held, parseUvPackages(after));
    assert.deepStrictEqual(
      downgrades,
      [],
      `The lock in ${folder} lowered: ${downgrades.join(', ')}`,
    );
    changes.push(...changedPackages(held, parseUvPackages(after)));
    projects.push(folder);
  }
  runOrThrow('bash', ['scripts/each-python-project.sh', 'uv', 'lock', '--check']);
  return { changes, projects };
}

function bumpTextFiles(pattern, apply) {
  const before = readFiles(trackedFiles(pattern));
  let after = before;
  for (const { name, to, data } of entry.members) {
    after = { ...after, ...apply(after, { name, to, data }) };
  }
  const projects = Object.keys(after).filter((path) => after[path] !== before[path]);
  for (const path of projects) {
    writeFileSync(path, after[path]);
  }
  return {
    changes: entry.members.map(({ name, from, to }) => ({ name, from: [from], to: [to] })),
    projects,
  };
}

const bumpers = {
  npm: bumpNpm,
  uv: bumpUv,
  actions: () => bumpTextFiles(ACTION_FILES, applyActions),
  docker: () => bumpTextFiles(DOCKERFILES, applyDocker),
};
assert.ok(entry.ecosystem in bumpers, `Unknown ecosystem ${entry.ecosystem}`);
const { changes, projects } = bumpers[entry.ecosystem]();
const files = runOrThrow('git', ['diff', '--name-only']).split('\n').filter(Boolean);
const outputs = [`changed=${files.length > 0}`];

if (files.length > 0) {
  const title = renderTitle(entry, commitScope(files, readFileSync('.gitcommitizen', 'utf8')));
  if (run('cz', ['--version']).status === 0) {
    const lint = run('cz', ['--no-breaking-footer', 'lint', '--paths', files.join('\n')], {
      input: title,
    });
    assert.strictEqual(
      lint.status,
      0,
      `cz rejects the title "${title}":\n${lint.stdout}${lint.stderr}`,
    );
  }
  const outDirectory = process.env.RUNNER_TEMP ?? tmpdir();
  writeFileSync(join(outDirectory, 'pr-title.txt'), title);
  writeFileSync(
    join(outDirectory, 'pr-body.md'),
    renderBody({ entry, changes, projects, cooldownDays: config.cooldownDays }),
  );
  console.log(title);
}

if (process.env.GITHUB_OUTPUT) {
  appendFileSync(process.env.GITHUB_OUTPUT, `${outputs.join('\n')}\n`);
}
