import assert from 'node:assert';
import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { applyActions } from './actions.mjs';
import { pnpmCommands, uvLockArgs } from './bump.mjs';
import { applyDocker } from './docker.mjs';
import {
  findDowngrades,
  findMissing,
  hasUvCooldown,
  normalizeName,
  parseUvPackages,
  pinEdit,
  restoreUvLockHeader,
} from './locks.mjs';
import { changedFiles, lockFiles, renderPr } from './pr.mjs';
import {
  ACTION_FILES,
  config,
  DOCKERFILES,
  readFiles,
  releaseAge,
  TERRAFORM_FILES,
  trackedFiles,
  uvProjectFolders,
} from './repo.mjs';
import { run, runOrThrow, sandboxEnv } from './run.mjs';
import { applyTerraform, parseProviders } from './terraform.mjs';
import { generateLock, LOCK_FILE, mergeLockBlock } from './terraform-lock.mjs';
import { compareVersions, newestVersion } from './versions.mjs';

const entry = JSON.parse(process.env.ENTRY);

function bumpNpm() {
  for (const [command, ...args] of pnpmCommands(entry, releaseAge)) {
    runOrThrow(command, args);
  }
  runOrThrow('pnpm', ['dedupe', '--ignore-scripts', '--loglevel', 'error', releaseAge]);
}

function bumpUv() {
  const folders = uvProjectFolders();
  const pyprojects = new Map(
    folders.map((folder) => [folder, readFileSync(`${folder}/pyproject.toml`, 'utf8')]),
  );
  const cooldownFlag = (folder) =>
    hasUvCooldown(pyprojects.get(folder)) ? [] : ['--exclude-newer', `${config.cooldownDays} days`];
  for (const [folder, text] of pyprojects) {
    const edited = entry.members.reduce(
      (current, { name, to }) => pinEdit(current, normalizeName(name), to),
      text,
    );
    if (edited !== text) {
      writeFileSync(`${folder}/pyproject.toml`, edited);
    }
  }
  for (const folder of folders) {
    const before = readFileSync(`${folder}/uv.lock`, 'utf8');
    const held = parseUvPackages(before);
    const behind = entry.members.filter(
      ({ name, to }) => held.has(name) && compareVersions(newestVersion(held.get(name)), to) < 0,
    );
    if (behind.length === 0) {
      continue;
    }
    runOrThrow('uv', uvLockArgs(behind, cooldownFlag(folder)), { cwd: folder, env: sandboxEnv() });
    const after = restoreUvLockHeader(readFileSync(`${folder}/uv.lock`, 'utf8'), before);
    writeFileSync(`${folder}/uv.lock`, after);
    const missing = findMissing(
      parseUvPackages(after),
      behind.map(({ name }) => name),
    );
    assert.deepStrictEqual(missing, [], `The lock in ${folder} lost: ${missing.join(', ')}`);
    const downgrades = findDowngrades(held, parseUvPackages(after));
    assert.deepStrictEqual(
      downgrades,
      [],
      `The lock in ${folder} lowered: ${downgrades.join(', ')}`,
    );
  }
  runOrThrow('bash', ['scripts/each-python-project.sh', 'uv', 'lock', '--check'], {
    env: sandboxEnv(),
  });
}

function bumpTextFiles(pattern, apply) {
  const before = readFiles(trackedFiles(pattern));
  let after = before;
  for (const { name, to, data } of entry.members) {
    after = { ...after, ...apply(after, { name, to, data }) };
  }
  for (const path of Object.keys(after).filter((path) => after[path] !== before[path])) {
    writeFileSync(path, after[path]);
  }
}

function bumpTerraform() {
  bumpTextFiles(TERRAFORM_FILES, applyTerraform);
  for (const { to, data } of entry.members) {
    const generated = generateLock({
      source: data.source,
      version: to,
      platforms: config.terraformPlatforms,
    });
    for (const path of trackedFiles(TERRAFORM_FILES)) {
      const provider = parseProviders(readFileSync(path, 'utf8')).providers.find(
        ({ source }) => source === data.source,
      );
      const lockPath = join(dirname(path), LOCK_FILE);
      const before = existsSync(lockPath) ? readFileSync(lockPath, 'utf8') : null;
      const merged = provider && mergeLockBlock(before, generated, provider.constraint);
      if (provider && merged !== before) {
        writeFileSync(lockPath, merged);
        runOrThrow('git', ['add', '--intent-to-add', lockPath]);
      }
    }
  }
}

const bumpers = {
  npm: bumpNpm,
  uv: bumpUv,
  actions: () => bumpTextFiles(ACTION_FILES, applyActions),
  docker: () => bumpTextFiles(DOCKERFILES, applyDocker),
  terraform: bumpTerraform,
};
assert.ok(entry.ecosystem in bumpers, `Unknown ecosystem ${entry.ecosystem}`);
const lockBefore = lockFiles(entry.ecosystem);
bumpers[entry.ecosystem]();
const files = changedFiles();
const outputs = [`changed=${files.length > 0}`];

if (files.length > 0) {
  const { title } = renderPr({
    entry,
    files,
    before: lockBefore,
    after: lockFiles(entry.ecosystem),
    gitcommitizen: readFileSync('.gitcommitizen', 'utf8'),
    cooldownDays: config.cooldownDays,
  });
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
  const outDirectory = join(process.env.RUNNER_TEMP ?? tmpdir(), 'patch');
  mkdirSync(outDirectory, { recursive: true });
  writeFileSync(join(outDirectory, 'changes.patch'), runOrThrow('git', ['diff', '--binary']));
  console.log(title);
}

if (process.env.GITHUB_OUTPUT) {
  appendFileSync(process.env.GITHUB_OUTPUT, `${outputs.join('\n')}\n`);
}
