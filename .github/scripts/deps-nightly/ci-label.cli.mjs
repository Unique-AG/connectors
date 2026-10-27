import { FAILED_LABEL, failureLabelAction } from './ci-label.mjs';
import { runOrThrow } from './run.mjs';

const LABELS = [
  [FAILED_LABEL, 'd93f0b', 'The CI of a dependency update failed'],
  ['deps-needs-human', 'b60205', 'A dependency update that a person must finish'],
  ['deps-fix-attempt-1', 'fbca04', 'The first automatic fix of a dependency update'],
  ['deps-fix-attempt-2', 'fbca04', 'The second automatic fix of a dependency update'],
];

for (const [name, color, description] of LABELS) {
  runOrThrow('gh', [
    'label',
    'create',
    name,
    '--color',
    color,
    '--description',
    description,
    '--force',
  ]);
}

const headSha = process.env.HEAD_SHA;
const runs = JSON.parse(
  runOrThrow('gh', [
    'run',
    'list',
    '--commit',
    headSha,
    '--limit',
    '100',
    '--json',
    'workflowName,conclusion',
  ]),
);

for (const number of JSON.parse(process.env.PULL_REQUESTS)) {
  const pullRequest = JSON.parse(
    runOrThrow('gh', ['pr', 'view', String(number), '--json', 'labels,headRefOid']),
  );
  const labels = pullRequest.labels.map(({ name }) => name);
  if (!labels.includes('dependencies') || pullRequest.headRefOid !== headSha) {
    continue;
  }
  const action = failureLabelAction(runs, labels);
  if (action !== 'none') {
    runOrThrow('gh', [
      'pr',
      'edit',
      String(number),
      action === 'add' ? '--add-label' : '--remove-label',
      FAILED_LABEL,
    ]);
    console.log(`#${number}: ${action} ${FAILED_LABEL}`);
  }
}
