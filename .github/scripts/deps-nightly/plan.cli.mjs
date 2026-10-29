import assert from 'node:assert';
import { appendFileSync, existsSync, readFileSync, writeFileSync } from 'node:fs';
import { createActionsLookup, planActions } from './actions.mjs';
import { createDockerLookup, planDocker } from './docker.mjs';
import {
  hasUvCooldown,
  parseRequirements,
  pinnedVersion,
  transitiveUpdates,
  uvFolderUpdates,
} from './locks.mjs';
import { createNpmDeprecationLookup, dropDeprecated } from './npm-deprecated.mjs';
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
  TERRAFORM_LOCKS,
  trackedFiles,
  uvProjectFolders,
} from './repo.mjs';
import { run, runOrThrow, sandboxEnv } from './run.mjs';
import { closedBodiesOf, closedKeysOf } from './state.mjs';
import { createTerraformLookup, planTerraform } from './terraform.mjs';

const CLOSED_PULLS_QUERY = `query($owner: String!, $name: String!, $endCursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: CLOSED, labels: ["dependencies"], first: 100, after: $endCursor) {
      nodes { body labels(first: 20) { nodes { name } } }
      pageInfo { hasNextPage endCursor }
    }
  }
}`;

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
  let updates;
  try {
    const updateRun = run('pnpm', [
      'update',
      '-r',
      '--lockfile-only',
      '--loglevel',
      'error',
      releaseAge,
    ]);
    updates = transitiveUpdates({
      result: updateRun,
      before,
      after: readFileSync('pnpm-lock.yaml', 'utf8'),
      cooldownDays: config.cooldownDays,
    });
  } finally {
    writeFileSync('pnpm-lock.yaml', before);
  }
  const { candidates, needsPerson } = npmCandidates({
    outdated: JSON.parse(outdatedRun.stdout.trim() || '{}'),
    lockChanges: updates.lockChanges,
    overrides: JSON.parse(readFileSync('package.json', 'utf8')).pnpm?.overrides ?? {},
  });
  return { candidates, needsPerson: [...updates.needsPerson, ...needsPerson] };
}

async function planUv() {
  const folders = uvProjectFolders();
  const pyprojects = Object.fromEntries(
    folders.map((folder) => [folder, readFileSync(`${folder}/pyproject.toml`, 'utf8')]),
  );
  const folderUpdates = folders.map((folder) => {
    const flag = hasUvCooldown(pyprojects[folder])
      ? []
      : ['--exclude-newer', `${config.cooldownDays} days`];
    const result = run('uv', ['lock', '--upgrade', '--dry-run', ...flag], {
      cwd: folder,
      env: sandboxEnv(),
    });
    return { folder, ...uvFolderUpdates({ result, folder, cooldownDays: config.cooldownDays }) };
  });
  const updates = new Map(folderUpdates.map(({ folder, updates }) => [folder, updates]));
  const blocked = folderUpdates.flatMap(({ needsPerson }) => needsPerson);
  const pinnedNames = [
    ...new Set(
      Object.values(pyprojects).flatMap((text) =>
        parseRequirements(text)
          .filter(({ spec }) => pinnedVersion(spec))
          .map(({ name }) => name),
      ),
    ),
  ];
  const { latest, needsPerson: unanswered } = await latestEligibleVersions(
    pinnedNames,
    async (name) => {
      const response = await fetch(`https://pypi.org/pypi/${name}/json`);
      return response.ok ? response.json() : undefined;
    },
    Date.now(),
    config.cooldownDays,
  );
  const { candidates, needsPerson } = uvCandidates({
    projects: folders.map((folder) => ({
      project: folder,
      pyproject: pyprojects[folder],
      lock: readFileSync(`${folder}/uv.lock`, 'utf8'),
      updates: updates.get(folder) ?? [],
    })),
    latest,
  });
  return { candidates, needsPerson: [...blocked, ...unanswered, ...needsPerson] };
}

function planFiles(pattern) {
  return readFiles(trackedFiles(pattern));
}

const ecosystemOptions = { now: Date.now(), cooldownDays: config.cooldownDays };
const npmPlan = planNpm();
const checkedNpm = await dropDeprecated({
  candidates: npmPlan.candidates,
  lookup: createNpmDeprecationLookup(),
});
const npm = {
  candidates: checkedNpm.candidates,
  needsPerson: [...npmPlan.needsPerson, ...checkedNpm.needsPerson],
};
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
  locks: planFiles(TERRAFORM_LOCKS),
  lookup: createTerraformLookup(process.env.GH_TOKEN),
  ...ecosystemOptions,
});
const repository = process.env.GITHUB_REPOSITORY;
const baseBranch = process.env.BASE_BRANCH ?? 'main';
const gh = (...args) => runOrThrow('gh', args);
const openPullRequests = JSON.parse(
  gh('pr', 'list', '--state', 'open', '--limit', '500', '--json', 'number,headRefName,body,labels'),
);
const openPulls = openPullRequests
  .filter(({ headRefName }) => headRefName.startsWith('deps/'))
  .map(({ number, headRefName, body, labels }) => ({
    number,
    branch: headRefName,
    body,
    labels: labels.map(({ name }) => name),
    behindBy: Number(
      gh('api', `repos/${repository}/compare/${baseBranch}...${headRefName}`, '--jq', '.behind_by'),
    ),
    humanCommits: JSON.parse(
      gh('pr', 'view', String(number), '--json', 'commits', '--jq', '[.commits[].authors[].login]'),
    ).some((login) => login !== 'github-actions[bot]'),
  }));
const [owner, repositoryName] = repository.split('/');
const closedBodies = closedBodiesOf(
  JSON.parse(
    gh(
      'api',
      'graphql',
      '--paginate',
      '--slurp',
      '-f',
      `query=${CLOSED_PULLS_QUERY}`,
      '-f',
      `owner=${owner}`,
      '-f',
      `name=${repositoryName}`,
    ),
  ),
);
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
  openPulls,
  closedKeys: closedKeysOf(closedBodies),
});

const summary = renderSummary(plan, process.env.PLAN_NOTE ?? '');
if (process.env.GITHUB_STEP_SUMMARY) {
  appendFileSync(process.env.GITHUB_STEP_SUMMARY, `${summary}\n`);
}
if (process.env.DASHBOARD_FILE) {
  const openList = openPulls.map(({ number, branch }) => `#${number} \`${branch}\``);
  writeFileSync(
    process.env.DASHBOARD_FILE,
    `${summary}\n### Open dependency pull requests (${openList.length})\n\n${openList.map((item) => `- ${item}`).join('\n')}\n`,
  );
}
if (process.env.GITHUB_OUTPUT) {
  appendFileSync(
    process.env.GITHUB_OUTPUT,
    `entries=${JSON.stringify(plan.entries)}\nupdates=${JSON.stringify(plan.updates)}\n`,
  );
}
console.log(summary);
console.log(JSON.stringify(plan.entries));
