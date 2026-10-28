import assert from 'node:assert';
import { appendFileSync, existsSync, readFileSync, writeFileSync } from 'node:fs';
import { createActionsLookup, planActions } from './actions.mjs';
import { createDockerLookup, planDocker } from './docker.mjs';
import {
  changedPackages,
  hasUvCooldown,
  parsePnpmPackages,
  parseRequirements,
  parseUvDryRun,
  pinnedVersion,
} from './locks.mjs';
import {
  buildPlan,
  latestEligibleVersions,
  npmCandidates,
  renderSummary,
  uvCandidates,
} from './plan.mjs';
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
import { createTerraformLookup, planTerraform } from './terraform.mjs';

function planNpm() {
  const outdatedRun = run('pnpm', [
    'outdated',
    '-r',
    '--format',
    'json',
    '--loglevel',
    'error',
    releaseAge,
  ]);
  assert.ok(
    outdatedRun.stdout.trim().startsWith('{') || outdatedRun.status === 0,
    `pnpm outdated failed:\n${outdatedRun.stdout}${outdatedRun.stderr}`,
  );
  const before = readFileSync('pnpm-lock.yaml', 'utf8');
  runOrThrow('pnpm', ['update', '-r', '--lockfile-only', '--loglevel', 'error', releaseAge]);
  const after = readFileSync('pnpm-lock.yaml', 'utf8');
  writeFileSync('pnpm-lock.yaml', before);
  return npmCandidates({
    outdated: JSON.parse(outdatedRun.stdout.trim() || '{}'),
    lockChanges: changedPackages(parsePnpmPackages(before), parsePnpmPackages(after)),
    overrides: JSON.parse(readFileSync('package.json', 'utf8')).pnpm?.overrides ?? {},
  });
}

async function planUv() {
  const folders = uvProjectFolders();
  const pyprojects = Object.fromEntries(
    folders.map((folder) => [folder, readFileSync(`${folder}/pyproject.toml`, 'utf8')]),
  );
  const flag = hasUvCooldown(Object.values(pyprojects))
    ? ''
    : `--exclude-newer "${config.cooldownDays} days"`;
  const dryRun = run(
    'bash',
    ['-c', `bash scripts/each-python-project.sh uv lock --upgrade --dry-run ${flag} 2>&1`],
    { env: sandboxEnv() },
  );
  assert.strictEqual(dryRun.status, 0, `uv lock --dry-run failed:\n${dryRun.stdout}`);
  const updates = parseUvDryRun(dryRun.stdout);
  const pinnedNames = [
    ...new Set(
      Object.values(pyprojects).flatMap((text) =>
        parseRequirements(text)
          .filter(({ spec }) => pinnedVersion(spec))
          .map(({ name }) => name),
      ),
    ),
  ];
  const latest = await latestEligibleVersions(
    pinnedNames,
    async (name) => {
      const response = await fetch(`https://pypi.org/pypi/${name}/json`);
      return response.ok ? response.json() : undefined;
    },
    Date.now(),
    config.cooldownDays,
  );
  return uvCandidates({
    projects: folders.map((folder) => ({
      project: folder,
      pyproject: pyprojects[folder],
      lock: readFileSync(`${folder}/uv.lock`, 'utf8'),
      updates: updates.get(folder) ?? [],
    })),
    latest,
  });
}

function planFiles(pattern) {
  return readFiles(trackedFiles(pattern));
}

const ecosystemOptions = { now: Date.now(), cooldownDays: config.cooldownDays };
const npm = planNpm();
const uv = await planUv();
const ledgerPath = process.env.TAG_LEDGER;
const actions = await planActions({
  files: planFiles(ACTION_FILES),
  lookup: createActionsLookup(process.env.GH_TOKEN),
  ledger: ledgerPath && existsSync(ledgerPath) ? JSON.parse(readFileSync(ledgerPath, 'utf8')) : {},
  ...ecosystemOptions,
});
if (ledgerPath) {
  writeFileSync(ledgerPath, JSON.stringify(actions.ledger));
}
const docker = await planDocker({
  files: planFiles(DOCKERFILES),
  lookup: createDockerLookup(),
  ...ecosystemOptions,
});
const terraform = await planTerraform({
  files: planFiles(TERRAFORM_FILES),
  lookup: createTerraformLookup(process.env.GH_TOKEN),
  ...ecosystemOptions,
});
const openPullRequests = JSON.parse(
  runOrThrow('gh', [
    'pr',
    'list',
    '--state',
    'open',
    '--limit',
    '500',
    '--json',
    'headRefName,title,labels',
  ]),
);
const openBranches = openPullRequests.map(({ headRefName }) => headRefName);
const patchTitles = openPullRequests
  .filter(({ labels }) => labels.some(({ name }) => name === 'vulna-squash'))
  .map(({ title }) => title);
const plan = buildPlan({
  candidates: [
    ...npm.candidates,
    ...uv.candidates,
    ...actions.candidates,
    ...docker.candidates,
    ...terraform.candidates,
  ],
  needsPerson: [
    ...npm.needsPerson,
    ...uv.needsPerson,
    ...actions.needsPerson,
    ...docker.needsPerson,
    ...terraform.needsPerson,
  ],
  config,
  openBranches,
  patchTitles,
});

const summary = renderSummary(plan, process.env.PLAN_NOTE ?? '');
const entries = JSON.stringify(plan.entries);
if (process.env.GITHUB_STEP_SUMMARY) {
  appendFileSync(process.env.GITHUB_STEP_SUMMARY, `${summary}\n`);
}
if (process.env.GITHUB_OUTPUT) {
  appendFileSync(process.env.GITHUB_OUTPUT, `entries=${entries}\n`);
}
console.log(summary);
console.log(entries);
