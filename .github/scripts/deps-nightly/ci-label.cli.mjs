import { FAILED_LABEL, failureLabelAction, READY_LABEL, reviewLabelAction } from './ci-label.mjs';
import { runOrThrow } from './run.mjs';

const LABELS = [
  [FAILED_LABEL, 'd93f0b', 'Marks a dependency update with a failed CI.'],
  [READY_LABEL, '0e8a16', 'Marks a dependency update with a green CI that waits for the review.'],
  ['deps-reviewed', '0e8a16', 'Marks a dependency update that the agent reviewed.'],
  ['deps-human-needed', 'b60205', 'Marks a dependency update that a person must finish.'],
  ['deps-fix-attempt-1', 'fbca04', 'Marks the first automatic fix of a dependency update.'],
  ['deps-fix-attempt-2', 'fbca04', 'Marks the second automatic fix of a dependency update.'],
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
    'workflowName,status,conclusion',
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
  for (const [label, action] of [
    [FAILED_LABEL, failureLabelAction(runs, labels)],
    [READY_LABEL, reviewLabelAction(runs, labels)],
  ]) {
    if (action !== 'none') {
      runOrThrow('gh', [
        'pr',
        'edit',
        String(number),
        action === 'add' ? '--add-label' : '--remove-label',
        label,
      ]);
      console.log(`#${number}: ${action} ${label}`);
    }
  }
}
