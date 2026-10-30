import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { assertAllowedChanges, assertRequirementEdits, readChanges } from './patch.mjs';
import { changedFiles, lockFiles, renderPr } from './pr.mjs';
import { config, readFiles, trackedFiles } from './repo.mjs';
import { runOrThrow } from './run.mjs';

const entry = JSON.parse(process.env.ENTRY);
const { ecosystem, members } = entry;
const pyprojects = () => readFiles(trackedFiles(/(^|\/)pyproject\.toml$/));
const before = ecosystem === 'uv' ? pyprojects() : {};
const lockBefore = lockFiles(ecosystem);
const gitcommitizen = readFileSync('.gitcommitizen', 'utf8');

runOrThrow('git', ['apply', join(process.env.PATCH_DIR, 'changes.patch')]);
assertAllowedChanges({ ecosystem, ...readChanges() });
assertRequirementEdits({ members, before, after: ecosystem === 'uv' ? pyprojects() : {} });

const { title, body } = renderPr({
  entry,
  files: changedFiles(),
  before: lockBefore,
  after: lockFiles(ecosystem),
  gitcommitizen,
  cooldownDays: config.cooldownDays,
});
mkdirSync(process.env.PR_DIR, { recursive: true });
writeFileSync(join(process.env.PR_DIR, 'pr-title.txt'), title);
writeFileSync(join(process.env.PR_DIR, 'pr-body.md'), body);
