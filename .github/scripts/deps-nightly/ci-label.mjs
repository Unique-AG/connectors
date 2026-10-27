const WATCHED_WORKFLOWS = ['[CI] Python', '[CI] Services', '[CI] Packages'];
export const FAILED_LABEL = 'deps-ci-failed';
export const READY_LABEL = 'deps-review-ready';
const REVIEWED_LABEL = 'deps-reviewed';
const HUMAN_NEEDED_LABEL = 'deps-human-needed';

export function failureLabelAction(runs, labels) {
  const latest = new Map();
  for (const { workflowName, conclusion } of runs) {
    if (WATCHED_WORKFLOWS.includes(workflowName) && !latest.has(workflowName)) {
      latest.set(workflowName, conclusion);
    }
  }
  const failed = [...latest.values()].includes('failure');
  const labeled = labels.includes(FAILED_LABEL);
  if (failed && !labeled) {
    return 'add';
  }
  return !failed && labeled ? 'remove' : 'none';
}

export function reviewLabelAction(runs, labels) {
  const latest = new Map();
  for (const { workflowName, status, conclusion } of runs) {
    if (WATCHED_WORKFLOWS.includes(workflowName) && !latest.has(workflowName)) {
      latest.set(workflowName, { status, conclusion });
    }
  }
  const settled = [...latest.values()];
  const green =
    settled.length > 0 &&
    settled.every(({ status, conclusion }) => status === 'completed' && conclusion === 'success');
  const labeled = labels.includes(READY_LABEL);
  const done = labels.includes(REVIEWED_LABEL) || labels.includes(HUMAN_NEEDED_LABEL);
  if (green && !labeled && !done) {
    return 'add';
  }
  return !green && labeled ? 'remove' : 'none';
}
